#!/usr/bin/env python3
"""Exercise the real source preparer through legacy/warm patchset changes."""
from pathlib import Path
import difflib
import importlib.util
import json
import os
import subprocess
import tempfile

R = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('prepare', R/'scripts/prepare-xnu-patches.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def run(*args, cwd):
    return subprocess.check_output(args, cwd=cwd, stderr=subprocess.STDOUT)


def patch(name, before, after):
    return ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                      fromfile='a/'+name, tofile='b/'+name))


with tempfile.TemporaryDirectory(prefix='xnu-refresh-test-') as directory:
    root = Path(directory)
    ref = root/'refer/xnu';ref.mkdir(parents=True)
    run('git','init','--quiet',cwd=ref)
    # Fixture identity is local to this temporary repository, never global.
    run('git','config','user.name','Fixture',cwd=ref)
    run('git','config','user.email','fixture@users.noreply.github.com',cwd=ref)
    originals = {'bsd/vm/vm_unix.c':'base shared region\n',
                 'bsd/kern/kern_descrip.c':'base fcntl\n', 'unchanged.c':'stable\n'}
    for name, content in originals.items():
        target=ref/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(content)
    run('git','add','.',cwd=ref);run('git','commit','--quiet','-m','fixture pin',cwd=ref)
    revision=run('git','rev-parse','HEAD',cwd=ref).decode().strip()
    (root/'.cache').mkdir();work=root/'.cache/xnu-work'
    run('git','clone','--quiet','--shared',str(ref),str(work),cwd=root)
    patches=root/'patches/xnu';patches.mkdir(parents=True)
    native=root/'kits/NativePrelink/patches';native.mkdir(parents=True)
    canonical=patches/'zz-root-startup-timing.patch'
    old=patch('bsd/vm/vm_unix.c',originals['bsd/vm/vm_unix.c'],'old timing\n')
    canonical.write_text(old)
    run('git','apply',str(canonical),cwd=work)  # warm legacy: old applied, no stamp
    unchanged=work/'unchanged.c';os.utime(unchanged,ns=(1234567890000000000,)*2)
    stable_mtime=unchanged.stat().st_mtime_ns
    restored=work/'iokit/DriverKit/restored.h';restored.parent.mkdir(parents=True);restored.write_text('restored header')
    obj=root/'build/xnu/ios-obj/object.o';obj.parent.mkdir(parents=True);obj.write_text('object cache')
    sdk=root/'.cache/fakeroot/sdk';sdk.parent.mkdir(parents=True);sdk.write_text('SDK cache')
    obj_mtime=obj.stat().st_mtime_ns;sdk_mtime=sdk.stat().st_mtime_ns
    # Same patch filename, incompatible new contents (the observed failure).
    canonical.write_text(patch('bsd/vm/vm_unix.c',originals['bsd/vm/vm_unix.c'],'new timing\n')+
                         patch('bsd/kern/kern_descrip.c',originals['bsd/kern/kern_descrip.c'],'signature timing\n'))
    native_patch=native/'prelink.patch'
    native_patch.write_text(patch('bsd/vm/vm_unix.c','new timing\n','new timing\nprelink\n'))
    for direction in ([], ['--reverse']):
        failed=subprocess.run(['git','apply',*direction,'--check',str(canonical)],cwd=work,capture_output=True)
        assert failed.returncode, 'legacy forward/reverse check must reproduce failure'
    module.prepare(root,revision)
    assert (work/'bsd/vm/vm_unix.c').read_text()=='new timing\nprelink\n'
    assert (work/'bsd/kern/kern_descrip.c').read_text()=='signature timing\n'
    assert unchanged.stat().st_mtime_ns==stable_mtime
    assert restored.read_text()=='restored header'
    assert obj.stat().st_mtime_ns==obj_mtime and sdk.stat().st_mtime_ns==sdk_mtime
    stamp=work/'.git/unixnu-patchset.json'
    before={str(p.relative_to(work)):p.stat().st_mtime_ns for p in (work/'bsd/vm/vm_unix.c',work/'bsd/kern/kern_descrip.c',unchanged,stamp)}
    module.prepare(root,revision)
    assert all((work/p).stat().st_mtime_ns==mtime for p,mtime in before.items())
    # Changed patchset with identical final bytes must preserve all source mtimes.
    extra=patches/'00-added.patch'
    extra.write_text('diff --git a/new.c b/new.c\nnew file mode 100644\n--- /dev/null\n+++ b/new.c\n@@ -0,0 +1 @@\n+new file\n')
    module.prepare(root,revision)
    assert (work/'new.c').read_text()=='new file\n'
    assert all((work/p).stat().st_mtime_ns==mtime for p,mtime in before.items() if p!='.git/unixnu-patchset.json')
    extra.unlink();native_patch.unlink();module.prepare(root,revision)
    assert not (work/'new.c').exists()
    assert (work/'bsd/vm/vm_unix.c').read_text()=='new timing\n'
    # Failed staging must not alter the live tree or its successful stamp.
    previous_stamp=stamp.read_bytes();previous_source=(work/'bsd/vm/vm_unix.c').read_bytes()
    extra.write_text(patch('bsd/vm/vm_unix.c','wrong context\n','broken\n'))
    try:module.prepare(root,revision)
    except subprocess.CalledProcessError:pass
    else:raise AssertionError('invalid patch unexpectedly accepted')
    assert stamp.read_bytes()==previous_stamp
    assert (work/'bsd/vm/vm_unix.c').read_bytes()==previous_source
    extra.unlink()
    # Revision mismatch is rejected before touching the work tree.
    try:module.prepare(root,'0'*40)
    except RuntimeError:pass
    else:raise AssertionError('wrong pin accepted')
    assert stamp.read_bytes()==previous_stamp
    # Failure recovery uses the retained ownership manifest.
    state=json.loads(stamp.read_text());state['identity']=None;stamp.write_text(json.dumps(state))
    module.prepare(root,revision)
    assert json.loads(stamp.read_text())['identity']
    assert obj.stat().st_mtime_ns==obj_mtime and sdk.stat().st_mtime_ns==sdk_mtime
    # Pin changes update Git metadata/source additions without rewriting stable files.
    (ref/'next-pin.c').write_text('next pin\n')
    run('git','add','next-pin.c',cwd=ref);run('git','commit','--quiet','-m','next fixture pin',cwd=ref)
    next_revision=run('git','rev-parse','HEAD',cwd=ref).decode().strip()
    current_mtime=(work/'bsd/vm/vm_unix.c').stat().st_mtime_ns
    module.prepare(root,next_revision)
    assert run('git','rev-parse','HEAD',cwd=work).decode().strip()==next_revision
    assert (work/'next-pin.c').read_text()=='next pin\n'
    assert (work/'bsd/vm/vm_unix.c').stat().st_mtime_ns==current_mtime
    assert unchanged.stat().st_mtime_ns==stable_mtime
    assert obj.stat().st_mtime_ns==obj_mtime and sdk.stat().st_mtime_ns==sdk_mtime


    def scenario(name):
        sandbox=root/name;sandbox.mkdir();(sandbox/'refer').mkdir()
        (sandbox/'refer/xnu').symlink_to(ref,target_is_directory=True)
        (sandbox/'.cache').mkdir();live=sandbox/'.cache/xnu-work'
        run('git','clone','--quiet','--shared',str(ref),str(live),cwd=sandbox)
        patchdir=sandbox/'patches/xnu';patchdir.mkdir(parents=True)
        (patchdir/'zz-timing.patch').write_text(canonical.read_text())
        return sandbox,live,patchdir

    def reject_without_mutation(sandbox,live,reason):
        live_stamp=live/'.git/unixnu-patchset.json'
        stamp_data=live_stamp.read_bytes() if live_stamp.exists() else None
        source_data=(live/'unchanged.c').read_bytes()
        index_data=(live/'.git/index').read_bytes()
        try:module.prepare(sandbox,next_revision)
        except RuntimeError as error:assert reason in str(error),str(error)
        else:raise AssertionError('unsafe source update unexpectedly accepted')
        assert (live/'unchanged.c').read_bytes()==source_data
        assert (live/'.git/index').read_bytes()==index_data
        assert (live_stamp.read_bytes() if live_stamp.exists() else None)==stamp_data

    # A staged user addition is not an old managed source: keep bytes AND index.
    sandbox,live,patchdir=scenario('staged-unrelated')
    (live/'user.c').write_text('user staged bytes\n')
    run('git','add','user.c',cwd=live)
    old_index=(live/'.git/index').read_bytes()
    module.prepare(sandbox,next_revision)
    assert (live/'user.c').read_text()=='user staged bytes\n'
    assert (live/'.git/index').read_bytes()==old_index
    assert 'user.c' not in json.loads((live/'.git/unixnu-patchset.json').read_text())['paths']

    addition='diff --git a/new.c b/new.c\nnew file mode 100644\n--- /dev/null\n+++ b/new.c\n@@ -0,0 +1 @@\n+canonical addition\n'
    for staged_user in (False,True):
        sandbox,live,patchdir=scenario('collision-'+str(staged_user))
        (patchdir/'00-add.patch').write_text(addition)
        (live/'new.c').write_text('user owns this\n')
        if staged_user:run('git','add','new.c',cwd=live)
        reject_without_mutation(sandbox,live,'unowned existing')
        assert (live/'new.c').read_text()=='user owns this\n'
        assert (live/'bsd/vm/vm_unix.c').read_text()==originals['bsd/vm/vm_unix.c']

    # Legacy canonical additions with exactly matching bytes/type/mode may migrate.
    sandbox,live,patchdir=scenario('legacy-addition')
    (patchdir/'00-add.patch').write_text(addition)
    run('git','apply',str(patchdir/'00-add.patch'),cwd=live)
    addition_mtime=(live/'new.c').stat().st_mtime_ns
    module.prepare(sandbox,next_revision)
    assert (live/'new.c').stat().st_mtime_ns==addition_mtime
    assert 'new.c' in json.loads((live/'.git/unixnu-patchset.json').read_text())['paths']
    # Once stamped, a new unowned collision is rejected even if bytes match.
    (patchdir/'00-add.patch').write_text(addition.replace('new.c','later.c'))
    (live/'later.c').write_text('canonical addition\n')
    reject_without_mutation(sandbox,live,'unowned existing')
    assert (live/'new.c').exists()  # no managed deletion before all preflights pass

    # Parent symlinks cannot redirect writes outside the managed work tree.
    sandbox,live,patchdir=scenario('symlink-parent')
    external=root/'external';(external/'vm').mkdir(parents=True);(external/'kern').mkdir()
    (external/'vm/vm_unix.c').write_text('external sentinel\n')
    (external/'kern/kern_descrip.c').write_text('external signature sentinel\n')
    run('git','mv','bsd','saved-bsd',cwd=live)
    (live/'bsd').symlink_to(external,target_is_directory=True)
    reject_without_mutation(sandbox,live,'symlink in managed source parent')
    assert (external/'vm/vm_unix.c').read_text()=='external sentinel\n'
    assert (external/'kern/kern_descrip.c').read_text()=='external signature sentinel\n'
    assert not list(external.rglob('.unixnu-patch-*'))


script=(R/'scripts/build-xnu-4k-baseline.sh').read_text()
assert 'python3 scripts/prepare-xnu-patches.py --root "$ROOT" --revision "$XNU_COMMIT"' in script
assert 'for LATE_PATCH' not in script
print('PASS actual preparer: legacy old->new patch, ordered NativePrelink, unchanged mtimes, warm no-op, add/remove, failed apply isolation, pin validation, recovery, staged/untracked collision protection, external-symlink rejection, safe legacy additions; OBJ/SDK retained')
