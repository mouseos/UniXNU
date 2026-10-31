#!/usr/bin/env python3
"""Build the native Metal bridge (drivers/NativeMetal/bridge/NativeMetalBridge.rs): the pinned metal2vulkan runtime behind a C ABI, as a static library.

--target ios (default) cross-builds for arm64-apple-ios17.0, --target host for the macOS host simulation. The runtime's own example library
(runtime_examples.ll) and its function-constant fixture are assembled to AIR with llvm-as and embedded for the self-tests. Only generated build files hold local paths; nothing here
is committed. Output: build/native-metal-bridge/<target>/libnative_metal_bridge.a"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PIN = json.loads((ROOT / 'scripts/data/gpu-metal-vulkan-inputs.json').read_text())['translator']['commit']
SOURCE = ROOT / '.cache/gpu-reference/metal2vulkan'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--target', choices=['ios', 'host'], default='ios')
parser.add_argument('--portable-sha2', action='store_true', help='use software SHA2 on CPUs without confirmed SHA2 instructions')
parser.add_argument('--runtime-commit-trace', action='store_true', help='compile opt-in commit phase instrumentation')
parser.add_argument('--manifest-only', action='store_true',
                    help='write build/native-metal-bridge/Cargo.toml (patched source, fixtures) and stop before cargo, for `cargo fetch`')
args = parser.parse_args()
if subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip() != PIN:
    raise SystemExit('Translator revision differs from the qualified source pin')
PATCHES = [ROOT / 'drivers/NativeMetal/bridge/patches' / name for name in [
    '0001-optional-constant-output-members.patch', '0002-resource-wait-storage-dependencies.patch',
    '0003-cache-device-entry-point-priming.patch', '0004-fold-constant-global-field-loads.patch',
    '0005-keep-module-decodes-and-profile-fingerprints.patch', '0006-skip-draws-without-a-pipeline.patch',
    '0007-accept-two-plane-rgb-surfaces.patch', '0008-optional-memory-pool-size.patch',
    '0009-commit-phase-observer.patch']]
def canonical_diff(diff):
    # Independent patches touch disjoint files; Git orders the combined diff by
    # filename, rather than by the order the patches were applied.
    blocks = [block for block in re.split(r'(?=^diff --git )', diff, flags=re.M) if block]
    names = [block.splitlines()[0] for block in blocks]
    if len(set(names)) != len(names):
        raise SystemExit('Overlapping recorded patches require an explicit combined-source update')
    # Git chooses its hash abbreviation length from repository size/config.
    # These index hashes are redundant: the base revision is pinned and every
    # path, mode and line of the complete diff is compared below. Normalize only
    # index metadata so the same source is accepted on fresh macOS runners.
    ordered = ''.join(sorted(blocks, key=lambda block: block.splitlines()[0]))
    return re.sub(r'^index [0-9a-f]+\.\.[0-9a-f]+(?= |$)', 'index <base>..<result>', ordered, flags=re.M)


def source_diff():
    return canonical_diff(subprocess.check_output(
        ['git', '-C', str(SOURCE), 'diff', '--no-ext-diff', '--no-textconv', 'HEAD', '--'], text=True))


expected = ''
states = [expected]
for patch in PATCHES:
    expected += patch.read_text()
    states.append(canonical_diff(expected))
tree_diff = source_diff()
if tree_diff not in states:
    raise SystemExit('Translator source differs from the pinned revision plus its recorded patches')
for patch in PATCHES[states.index(tree_diff):]:
    subprocess.run(['git', '-C', str(SOURCE), 'apply', str(patch)], check=True)
if source_diff() != canonical_diff(expected):
    raise SystemExit('Translator patch result differs from its exact recorded source')
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
    '[features]', 'unixnu-commit-trace = ["metal2vulkan-runtime/unixnu-commit-trace"]',
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
    result = subprocess.run(['cargo', '+1.98.0', 'build', '--release', '--manifest-path', manifest, '--target', triple] +
                            (['--features', 'unixnu-commit-trace'] if args.runtime_commit_trace else []) + [
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
    'target': args.target, 'portable_sha2': args.portable_sha2, 'runtime_commit_trace': args.runtime_commit_trace,
    'translator': PIN, 'library_sha256': digest,
}, indent=2) + '\n')
print('PASS: native Metal bridge static library for %s (%d bytes); translator %s' % (args.target, final.stat().st_size, PIN[:12]))
