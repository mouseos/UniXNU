#!/usr/bin/env python3
"""Exercise the real builder with the pinned source and a small adversarial fixture."""
import argparse
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--base-translator', required=True, type=Path,
                    help='local Git repository containing the pinned translator commit')
args = parser.parse_args()
pin = '720ef1ce9ae2a2068999a8675717418b9416283e'
patches = sorted((ROOT/'drivers/NativeMetal/bridge/patches').glob('000[1-9]-*.patch'))
assert len(patches) == 9

def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)

def prepare(root, revision, patch_directory, real=False):
    scripts=root/'scripts';scripts.mkdir(parents=True);(scripts/'data').mkdir()
    shutil.copy2(ROOT/'scripts/build-native-metal-bridge.py', scripts)
    (scripts/'data/gpu-metal-vulkan-inputs.json').write_text(json.dumps({'translator': {'commit': revision}}))
    link=root/'drivers/NativeMetal/bridge/patches';link.parent.mkdir(parents=True);link.symlink_to(patch_directory.resolve())
    if real:
        shutil.copy2(ROOT/'scripts/data/native-metal-translator-trees.json', scripts/'data')
    else:
        source=root/'.cache/gpu-reference/metal2vulkan'
        env=dict(os.environ)
        with tempfile.TemporaryDirectory() as d:
            env['GIT_INDEX_FILE']=str(Path(d)/'index')
            cmd=['git','-C',str(source),'-c','apply.whitespace=nowarn']
            subprocess.run(cmd+['read-tree','HEAD'],env=env,check=True)
            trees=[subprocess.check_output(cmd+['write-tree'],env=env,text=True).strip()]
            selected=sorted(patch_directory.glob('000[1-9]-*.patch'))
            for patch in selected:
                subprocess.run(cmd+['apply','--cached','--whitespace=nowarn',str(patch)],env=env,check=True)
                trees.append(subprocess.check_output(cmd+['write-tree'],env=env,text=True).strip())
        manifest={'translator':revision,'trees':trees,'patches':[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in selected]}
        (scripts/'data/native-metal-translator-trees.json').write_text(json.dumps(manifest))
    return scripts/'build-native-metal-bridge.py'

def verify(builder, repo, ok):
    index=repo/'.git/index';before=index.read_bytes()
    objects=repo/'.git/objects'
    object_files={p.relative_to(objects) for p in objects.rglob('*') if p.is_file()}
    shared=set((repo/'.git').glob('sharedindex.*'))
    result=subprocess.run(['python3',str(builder),'--apply-and-verify-source-only'],capture_output=True,text=True)
    assert (result.returncode==0)==ok,(result.returncode,result.stdout[-1000:],result.stderr[-1000:])
    if not ok: assert 'Translator ' in result.stderr, result.stderr[-1000:]
    assert index.read_bytes()==before, 'verification changed the real Git index'
    assert {p.relative_to(objects) for p in objects.rglob('*') if p.is_file()}==object_files, 'verification changed the real object store'
    assert set((repo/'.git').glob('sharedindex.*'))==shared, 'verification created a shared real index'

with tempfile.TemporaryDirectory(prefix='unixnu-metal-verifier-test-') as directory:
    temp=Path(directory)
    # The real runner sequence, using the exact source pin and all nine patches.
    root=temp/'real'; repo=root/'.cache/gpu-reference/metal2vulkan';repo.parent.mkdir(parents=True)
    subprocess.run(['git','clone','--quiet','--shared','--no-checkout',str(args.base_translator.resolve()),str(repo)],check=True)
    git(repo,'checkout','--quiet','--detach',pin)
    builder=prepare(root,pin,ROOT/'drivers/NativeMetal/bridge/patches',real=True)
    for patch in patches[:8]: git(repo,'apply',str(patch))
    verify(builder,repo,True)
    new=repo/'crates/metal2vulkan-runtime/src/encoder_open_trace.rs'
    assert new.is_file() and b'encoder_open_trace.rs' in git(repo,'ls-files','--others','--exclude-standard','-z').stdout
    first=new.read_bytes();verify(builder,repo,True);assert new.read_bytes()==first

    # A small local Git repo makes the adversarial cases fast while still
    # running the complete, unchanged builder entry point and all nine patches.
    fixture=temp/'fixture'; source=fixture/'.cache/gpu-reference/metal2vulkan';source.mkdir(parents=True)
    git(source,'init','-q')
    email=git(source,'config','user.email').stdout.decode().strip()
    assert email.endswith('@users.noreply.github.com'), 'Git identity must be a GitHub noreply address'
    for i in range(8): (source/f'old{i}.rs').write_text(f'base {i}\n')
    (source/'untouched.rs').write_text('unmodified\n')
    (source/'.gitattributes').write_text('*.bin -diff\nuntouched.rs text eol=lf\n')
    (source/'.gitignore').write_text('hidden-extra\n/target/\n')
    git(source,'add','.')
    git(source,'commit','-q','-m','fixture')
    fixture_pin=git(source,'rev-parse','HEAD').stdout.decode().strip()
    patchdir=temp/'fixture-patches';patchdir.mkdir()
    for i in range(8):
        path=source/f'old{i}.rs';path.write_text(f'base {i}\nmodified {i}\n')
        (patchdir/patches[i].name).write_bytes(git(source,'diff','--',path.name).stdout)
        git(source,'checkout','--',path.name)
    added=source/'new.rs';added.write_text('recorded\nsource\n');git(source,'add','-N','--','new.rs')
    (patchdir/patches[8].name).write_bytes(git(source,'diff','--','new.rs').stdout)
    git(source,'reset','-q','HEAD','--','new.rs');added.unlink()
    builder=prepare(fixture,fixture_pin,patchdir)
    # 0→9 and already-applied retry, preserving genuine untracked status.
    verify(builder,source,True); assert b'new.rs' in git(source,'ls-files','--others','--exclude-standard','-z').stdout
    verify(builder,source,True); original=added.read_bytes()
    (source/'.git/info/exclude').write_text('new.rs\n')
    verify(builder,source,True)  # Expected new source must be seen even if ignored.
    (source/'.git/info/exclude').write_text('')
    added.write_bytes(original+b'extra\n');verify(builder,source,False);added.write_bytes(original)
    added.write_bytes(b'\x00\xffunexpected');verify(builder,source,False);added.write_bytes(original)
    tracked=source/'old0.rs';content=tracked.read_bytes();tracked.write_bytes(content+b'extra\n');verify(builder,source,False);tracked.write_bytes(content)
    git(source,'config','core.autocrlf','true')
    added.write_bytes(original.replace(b'\n',b'\r\n'));verify(builder,source,False);added.write_bytes(original)
    untouched=source/'untouched.rs'; u=untouched.read_bytes()
    untouched.write_bytes(u.replace(b'\n',b'\r\n'));verify(builder,source,False);untouched.write_bytes(u)
    git(source,'config','core.autocrlf','false')
    git(source,'config','core.filemode','false')
    mode=tracked.stat().st_mode;tracked.chmod(mode|0o111);verify(builder,source,False);tracked.chmod(mode)
    mode=untouched.stat().st_mode;untouched.chmod(mode|0o111);verify(builder,source,False);untouched.chmod(mode)
    git(source,'config','core.filemode','true')
    for name,data in [('unrelated-empty',b''),('unrelated-binary.bin',b'\x00\xff'),
                      (':(exclude)literal',b'unexpected'),('line\nbreak',b'unexpected'),('hidden-extra',b'ignored')]:
        extra=source/name;extra.write_bytes(data);verify(builder,source,False);extra.unlink()
    if hasattr(os,'symlink'):
        extra=source/'unrelated-link';extra.symlink_to('missing');verify(builder,source,False);extra.unlink()
    extra=source/'staged-extra';extra.write_text('unexpected');git(source,'add','staged-extra')
    verify(builder,source,False);git(source,'reset','-q','HEAD','--','staged-extra');extra.unlink()
    (source/'target').mkdir();(source/'target/artifact').write_text('output');verify(builder,source,True)
    shutil.rmtree(source/'target')
    nested=source/'nested/target';nested.mkdir(parents=True);(nested/'input').write_text('unexpected');verify(builder,source,False);shutil.rmtree(source/'nested')
    (source/'target').symlink_to('missing');verify(builder,source,False);(source/'target').unlink()
    verify(builder,source,True)
    manifest_path=fixture/'scripts/data/native-metal-translator-trees.json'
    manifest=json.loads(manifest_path.read_text());saved=manifest_path.read_text()
    manifest['trees'][-1]='0'*40;manifest_path.write_text(json.dumps(manifest));verify(builder,source,False)
    manifest=json.loads(saved);manifest['patches'][8]['sha256']='0'*64;manifest_path.write_text(json.dumps(manifest));verify(builder,source,False)
    manifest_path.write_text(saved)

print('PASS: real builder 8→9/retry; fixture 0→9, exact bytes/modes, ignored and unrelated files, real index preserved')
