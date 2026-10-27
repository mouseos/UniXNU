#!/usr/bin/env python3
"""Build the native Metal bridge (drivers/NativeMetal/bridge/NativeMetalBridge.rs): the pinned metal2vulkan runtime behind a C ABI, as a static library.

--target ios (default) cross-builds for arm64-apple-ios17.0, --target host for the macOS host simulation. The runtime's own example library
(runtime_examples.ll) and its function-constant fixture are assembled to AIR with llvm-as and embedded for the self-tests. Only generated build files hold local paths; nothing here
is committed. Output: build/native-metal-bridge/<target>/libnative_metal_bridge.a"""
import argparse
import hashlib
import json
import os
import stat
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PIN = json.loads((ROOT / 'scripts/data/gpu-metal-vulkan-inputs.json').read_text())['translator']['commit']
SOURCE = ROOT / '.cache/gpu-reference/metal2vulkan'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--target', choices=['ios', 'host'], default='ios')
parser.add_argument('--portable-sha2', action='store_true', help='use software SHA2 on CPUs without confirmed SHA2 instructions')
parser.add_argument('--apply-and-verify-source-only', action='store_true',
                    help='verify/apply the pinned translator patches and stop before SDK tools or build output')
parser.add_argument('--manifest-only', action='store_true',
                    help='write build/native-metal-bridge/Cargo.toml (patched source, fixtures) and stop before cargo, for `cargo fetch`')
args = parser.parse_args()
def git_environment():
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_ATTR_NOSYSTEM='1', GIT_OPTIONAL_LOCKS='0', GIT_NO_REPLACE_OBJECTS='1')
    return env


def checked_git(*args):
    return subprocess.check_output(['git', '-C', str(SOURCE), *args], env=git_environment(), text=True).strip()


if Path(checked_git('rev-parse', '--show-toplevel')).resolve() != SOURCE.resolve():
    raise SystemExit('Translator source must be its own Git repository')
if checked_git('rev-parse', '--show-object-format') != 'sha1' or checked_git('rev-parse', 'HEAD') != PIN:
    raise SystemExit('Translator revision differs from the qualified source pin')
PATCHES = [ROOT / 'drivers/NativeMetal/bridge/patches' / name for name in [
    '0001-optional-constant-output-members.patch', '0002-resource-wait-storage-dependencies.patch',
    '0003-cache-device-entry-point-priming.patch', '0004-fold-constant-global-field-loads.patch',
    '0005-keep-module-decodes-and-profile-fingerprints.patch', '0006-skip-draws-without-a-pipeline.patch',
    '0007-accept-two-plane-rgb-surfaces.patch', '0008-optional-memory-pool-size.patch',
    '0009-encoder-open-trace.patch']]
TREE_MANIFEST = json.loads((ROOT / 'scripts/data/native-metal-translator-trees.json').read_text())
if (TREE_MANIFEST['translator'] != PIN or len(TREE_MANIFEST['trees']) != len(PATCHES) + 1 or
        [(entry['name'], entry['sha256']) for entry in TREE_MANIFEST['patches']] !=
        [(patch.name, hashlib.sha256(patch.read_bytes()).hexdigest()) for patch in PATCHES]):
    raise SystemExit('Translator patch manifest differs from recorded inputs')
if checked_git('rev-parse', 'HEAD^{tree}') != TREE_MANIFEST['trees'][0]:
    raise SystemExit('Translator base tree differs from recorded source')
def apply_recorded_patches():
    # Work with a private index and object store. Reconstruct each legal prefix
    # from the pinned HEAD and exact patches, then compare raw file contents and
    # modes, including files unrelated to the patches. Never change the checkout's
    # index or object database, and never use Git clean filters to compare bytes.
    env = git_environment()
    git = ['git', '-C', str(SOURCE), '-c', 'core.splitIndex=false',
           '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false',
           '-c', 'core.sparseCheckout=false', '-c', 'core.autocrlf=false',
           '-c', 'core.safecrlf=false', '-c', 'core.eol=lf', '-c', 'core.attributesFile=' + os.devnull,
           '-c', 'apply.whitespace=nowarn', '--literal-pathspecs']
    obj = Path(subprocess.check_output(git + ['rev-parse', '--git-path', 'objects'], env=env, text=True).strip())
    if not obj.is_absolute():
        obj = SOURCE / obj
    with tempfile.TemporaryDirectory(prefix='unixnu-metal-verify-') as directory:
        temp = Path(directory)
        (temp / 'objects').mkdir()
        env.update(GIT_INDEX_FILE=str(temp / 'index'), GIT_OBJECT_DIRECTORY=str(temp / 'objects'),
                   GIT_ALTERNATE_OBJECT_DIRECTORIES=str(obj.resolve()))
        subprocess.run(git + ['read-tree', '--no-sparse-checkout', 'HEAD'], env=env, check=True)

        def index_entries():
            data = subprocess.check_output(git + ['ls-files', '--stage', '-z'], env=env)
            result = {}
            for entry in filter(None, data.split(b'\0')):
                metadata, name = entry.split(b'\t', 1)
                mode, oid, stage = metadata.split(b' ')
                if stage != b'0' or mode not in (b'100644', b'100755', b'120000'):
                    raise SystemExit('Unsupported translator index entry or submodule')
                result[name] = (mode, oid)
            return result

        states = [index_entries()]
        if subprocess.check_output(git + ['write-tree'], env=env, text=True).strip() != TREE_MANIFEST['trees'][0]:
            raise SystemExit('Translator base tree differs from recorded source')
        for number, patch in enumerate(PATCHES, 1):
            subprocess.run(git + ['apply', '--cached', '--whitespace=nowarn', str(patch)], env=env, check=True)
            if subprocess.check_output(git + ['write-tree'], env=env, text=True).strip() != TREE_MANIFEST['trees'][number]:
                raise SystemExit('Translator patched tree differs from recorded source')
            states.append(index_entries())
        # The pinned tree has no tracked target/ files; allowing that directory
        # is safe only while Cargo output is explicitly directed elsewhere.
        if any(name.startswith(b'target/') for name in states[-1]):
            raise SystemExit('Translator tracks target/; verify its contents explicitly')

        directories = {}
        root_bytes = os.fsencode(SOURCE)
        def exact_path(name):
            parent = root_bytes
            for part in name.split(b'/'):
                if parent not in directories:
                    try:
                        directories[parent] = {entry.name for entry in os.scandir(parent)}
                    except OSError:
                        return False
                if part not in directories[parent]:
                    return False
                parent = os.path.join(parent, part)
            return True

        def actual_kind(path):
            try:
                info = os.lstat(path)
            except FileNotFoundError:
                return None
            if stat.S_ISLNK(info.st_mode):
                return b'120000'
            if stat.S_ISREG(info.st_mode):
                return b'100755' if info.st_mode & stat.S_IXUSR else b'100644'
            raise SystemExit('Unsupported translator worktree file type')

        def open_regular(path, expected_mode):
            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_CLOEXEC', 0)
            try:
                fd = os.open(path, flags)
            except OSError:
                raise SystemExit('Translator source bytes or modes differ from recorded patches') from None
            info = os.fstat(fd)
            mode = b'100755' if info.st_mode & stat.S_IXUSR else b'100644'
            if not stat.S_ISREG(info.st_mode) or mode != expected_mode:
                os.close(fd)
                raise SystemExit('Translator source bytes or modes differ from recorded patches')
            return os.fdopen(fd, 'rb')

        def actual_oid(name):
            if not exact_path(name):
                return None
            path = SOURCE / os.fsdecode(name)
            mode = actual_kind(path)
            if mode is None:
                return None
            if mode == b'120000':
                data = os.fsencode(os.readlink(path))
                digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest().encode()
            else:
                with open_regular(path, mode) as stream:
                    size = os.fstat(stream.fileno()).st_size
                    digestor = hashlib.sha1(b'blob ' + str(size).encode() + b'\0')
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digestor.update(chunk)
                digest = digestor.hexdigest().encode()
            return mode, digest

        # Prefixes can differ only in paths touched by the recorded patches.
        all_names = set().union(*(state.keys() for state in states))
        varying = [name for name in all_names if len({state.get(name) for state in states}) > 1]
        actual = {name: actual_oid(name) for name in varying}
        matches = [i for i, state in enumerate(states) if all(state.get(name) == actual[name] for name in varying)]
        if len(matches) != 1:
            raise SystemExit('Translator source differs from the pinned revision plus its recorded patches')
        count = matches[0]

        def verify_exact(expected):
            # The final synthetic index includes every recorded addition. Scan
            # ignored and non-ignored extras; only root target/ is disposable.
            extras = subprocess.check_output(git + ['ls-files', '--others', '--directory', '--no-empty-directory', '-z'], env=env)
            if any(name != b'target/' for name in filter(None, extras.split(b'\0'))):
                raise SystemExit('Translator source contains unrelated untracked files')
            batch = subprocess.Popen(git + ['cat-file', '--batch'], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            try:
                for name, (mode, oid) in expected.items():
                    path = SOURCE / os.fsdecode(name)
                    if not exact_path(name) or actual_kind(path) != mode:
                        raise SystemExit('Translator source bytes or modes differ from recorded patches')
                    batch.stdin.write(oid + b'\n'); batch.stdin.flush()
                    header = batch.stdout.readline().rstrip(b'\n').split(b' ')
                    if len(header) != 3 or header[0] != oid or header[1] != b'blob':
                        raise SystemExit('Cannot read expected translator blob')
                    left = int(header[2])
                    if mode == b'120000':
                        actual_data = os.fsencode(os.readlink(path))
                        expected_data = batch.stdout.read(left)
                        if len(expected_data) != left or actual_data != expected_data:
                            raise SystemExit('Translator source bytes or modes differ from recorded patches')
                    else:
                        with open_regular(path, mode) as stream:
                            while left:
                                expected_data = batch.stdout.read(min(left, 1024 * 1024))
                                if not expected_data or stream.read(len(expected_data)) != expected_data:
                                    raise SystemExit('Translator source bytes or modes differ from recorded patches')
                                left -= len(expected_data)
                            if stream.read(1):
                                raise SystemExit('Translator source bytes or modes differ from recorded patches')
                    if batch.stdout.read(1) != b'\n':
                        raise SystemExit('Cannot read expected translator blob')
            finally:
                for stream in (batch.stdin, batch.stdout):
                    try:
                        stream.close()
                    except (BrokenPipeError, OSError):
                        pass
                batch.wait()

        verify_exact(states[count])
        for patch in PATCHES[count:]:
            subprocess.run(git + ['apply', '--whitespace=nowarn', str(patch)], env=env, check=True)
        if count != len(PATCHES):
            directories.clear()  # `git apply` can add or remove entries.
            verify_exact(states[-1])


apply_recorded_patches()
if args.apply_and_verify_source_only:
    print('PASS: translator source matches its pinned revision and recorded patches')
    raise SystemExit(0)
out = ROOT / 'build/native-metal-bridge'
out.mkdir(parents=True, exist_ok=True)
llvm_as = next((p for p in ['/opt/homebrew/opt/llvm/bin/llvm-as', shutil.which('llvm-as') or ''] if p and Path(p).exists()), None)
if not llvm_as:
    raise SystemExit('llvm-as (LLVM 21 or newer) is required to assemble the fixture')
air = out / 'runtime_examples.air'
subprocess.run([llvm_as, '-o', air, SOURCE / 'crates/metal2vulkan-validation/fixtures/public/examples/runtime_examples.ll'], check=True)
fc_air = out / 'function_constant.air'
subprocess.run([llvm_as, '-o', fc_air, SOURCE / 'crates/metal2vulkan-validation/fixtures/public/kernel_function_constant_gate_fold.ll'], check=True)
manifest = out / 'Cargo.toml'
manifest.write_text('\n'.join([
    '[package]', 'name = "native-metal-bridge"', 'version = "0.1.0"', 'edition = "2024"', 'rust-version = "1.98"', '[workspace]',
    '[lib]', 'crate-type = ["staticlib"]', 'path = ' + json.dumps(str(ROOT / 'drivers/NativeMetal/bridge/NativeMetalBridge.rs')),
    '[dependencies]',
    'metal2vulkan = { path = ' + json.dumps(str(SOURCE / 'crates/metal2vulkan')) + ', features = ["ash"] }',
    'metal2vulkan-runtime = { path = ' + json.dumps(str(SOURCE / 'crates/metal2vulkan-runtime')) + ' }',
    'libc = "0.2"',
    # Apple cpufeatures assumes SHA2 instructions. Non-Apple boards may select
    # force-soft explicitly; it takes precedence even if another dependency enables asm.
    'sha2 = { version = "0.10", features = ' + json.dumps(['force-soft'] if args.portable_sha2 else ['asm']) + ' }',
    '[profile.release]', 'panic = "unwind"', 'debug = 1', '',
]))
if args.manifest_only:
    print(manifest)
    raise SystemExit(0)
triple = 'aarch64-apple-ios' if args.target == 'ios' else 'aarch64-apple-darwin'
env = dict(os.environ, NMB_FIXTURE_AIR=str(air), NMB_FC_AIR=str(fc_air), IPHONEOS_DEPLOYMENT_TARGET='17.0', MACOSX_DEPLOYMENT_TARGET='14.0')
target_dir = ROOT / 'build/m2v-target'
log = out / ('build-%s.log' % args.target)
with log.open('w') as stream:
    result = subprocess.run(['cargo', '+1.98.0', 'build', '--release', '--manifest-path', manifest, '--target', triple,
                             '--target-dir', target_dir], env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
if result.returncode:
    raise SystemExit(log.read_text()[-6000:])
library = target_dir / triple / 'release/libnative_metal_bridge.a'
final = out / args.target / 'libnative_metal_bridge.a'
final.parent.mkdir(exist_ok=True)
shutil.copyfile(library, final)
with final.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
final.with_suffix('.json').write_text(json.dumps({
    'target': args.target, 'portable_sha2': args.portable_sha2,
    'translator': PIN, 'library_sha256': digest,
}, indent=2) + '\n')
print('PASS: native Metal bridge static library for %s (%d bytes); translator %s' % (args.target, final.stat().st_size, PIN[:12]))
