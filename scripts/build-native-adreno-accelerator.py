#!/usr/bin/env python3
"""Build the staged AGXAccelerator class (drivers/NativeAdreno/NativeAdrenoAccelerator.cpp) against the audited original
IOAcceleratorES imports, as a "late" archive: its static initializer is removed from __mod_init_func and exported so the board
probe runs it after the original IOGPUFamily kext has loaded. Same binding recipe as build-native-accelerator-abi.py (exact
original constructor, destructor and metaclass addresses from build/gpu-analysis/ioaccelerator-base-abi.json).

--source FILE builds another accelerator class of the same shape instead (a device repository's GPU, for example
kits/<kit>/powervr/NativePowerVRAccelerator.cpp): a direct IOAcceleratorES subclass whose only original imports are the base's
constructor, destructor and metaclass. Its staged initializer is __GLOBAL__sub_I_<file name>, its archive
build/native-accelerator/<stem>/lib<stem>.late.a, and --into ARCHIVE adds it to that archive (the board archive that calls the
initializer) in place of libNativeAdreno.a. Without --source nothing changes."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--source', type=Path, help='accelerator source (default drivers/NativeAdreno/NativeAdrenoAccelerator.cpp)')
parser.add_argument('--into', type=Path, help='archive that receives the staged objects (with --source)')
options = parser.parse_args()
if options.into and not options.source:
    parser.error('--into goes with --source')
# Not resolved: kits/<kit> may be a link to the device repository, and the report names the source inside this tree.
source = ROOT / options.source if options.source else ROOT / 'drivers/NativeAdreno/NativeAdrenoAccelerator.cpp'
if not source.is_file():
    sys.exit('No accelerator source %s' % source)
OUT = ROOT / ('build/native-accelerator/' + source.stem if options.source else 'build/native-adreno-accelerator')
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / 'kits/NativePrelink'))
from native_prelink import macho


def run(cmd, **kw):
    return subprocess.check_output([str(x) for x in cmd], timeout=120, **kw)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


plan_path = ROOT / 'build/gpu-analysis/ioaccelerator-base-abi.json'
# The audit of the original base class needs the hardware-observed parent evidence of the audited kernel; its recorded result
# ships with the scripts and seeds a fresh tree.
recorded = ROOT / 'scripts/data/ioaccelerator-base-abi.json'
if not plan_path.exists() and recorded.exists():
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_bytes(recorded.read_bytes())
if not plan_path.exists():
    print(run(['python3', ROOT / 'scripts/audit-target-accelerator-base.py'], text=True), end='')
plan = json.loads(plan_path.read_text())
if plan['operational_overrides'] or plan['instance_bytes'] != 136 or plan['virtual_entries'] != 168:
    sys.exit('The audited original base is not the expected 136-byte, 168-entry class without operational overrides')

record = json.loads((ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))
obj = OUT / (source.stem + '.o')
cmd, i, args = [], 0, record['arguments']
while i < len(args):
    v = args[i]
    if v == record['file']:
        cmd.append(str(source))
    elif v == '-o':
        cmd += ['-o', str(obj)]
        i += 1
    elif v == '-Xclang' and args[i + 1].startswith('-W'):
        i += 1
    elif not v.startswith('-W') and v not in ('-MD', '-MP'):
        cmd.append(v)
    i += 1
    if v in ('-MF', '-MJ'):
        i += 1
# Older Xcode clang (26.3 and earlier) rejects -Wno-unnecessary-virtual-specifier under -Werror; pass it only when known.
UNNECESSARY_VIRTUAL = [flag for flag in ['-Wno-unnecessary-virtual-specifier'] if subprocess.run(
    ['xcrun', 'clang', '-x', 'c++', '-fsyntax-only', '-Werror=unknown-warning-option', flag, '-'],
    input=b'', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0]
cmd += ['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', *UNNECESSARY_VIRTUAL, '-Wno-c99-designator',
        '-Wno-reorder-init-list', '-Wno-deprecated-enum-enum-conversion', '-Wno-overloaded-virtual',
        '-I', str(ROOT / '.cache/xnu-work/osfmk'), '-I', str(ROOT / 'drivers/NativeMetal')]
subprocess.run(cmd, cwd=record['directory'], check=True)

raw = obj.read_bytes()
im = macho(raw)
st = next(p for c, p, _ in im['commands'] if c == 2)
at, count, strings, _ = struct.unpack_from('<4I', raw, st + 8)
symbols = []
for k in range(count):
    ix, kind, section, _, va = struct.unpack_from('<IBBHQ', raw, at + k * 16)
    symbols.append((raw[strings + ix:raw.index(b'\0', strings + ix)].decode(), va, kind))
bindings = {'__ZN15IOAcceleratorESC2EPK11OSMetaClass': int(plan['protected_compatible_constructor_aliases'][0], 16),
            '__ZN15IOAcceleratorESD2Ev': int(plan['nondeleting_destructor'], 16),
            '__ZN15IOAcceleratorES10gMetaClassE': int(plan['metaclass'], 16)}
undefined = {n for n, _, k in symbols if k == 1 and 'IOAcceleratorES' in n}
extra = undefined - set(bindings)
if extra or not undefined & set(bindings):
    sys.exit('Unexpected original-base imports: %s' % sorted(extra))
asm = OUT / 'original-bindings.S'
asm.write_text(''.join(f'.globl {n}\n.set {n}, {a:#x}\n' for n, a in sorted(bindings.items()) if n in undefined))
sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-isysroot', sdk, '-c', asm, '-o', OUT / 'original-bindings.o'])

llvm = Path(run(['brew', '--prefix', 'llvm'], text=True).strip()) / 'bin'
late = OUT / (source.stem + '.late.o')
run([llvm / 'llvm-objcopy', '--remove-section=__DATA,__mod_init_func',
     '--globalize-symbol=__GLOBAL__sub_I_' + source.name, obj, late])


def code(p):
    b = p.read_bytes()
    s = next(s for g in macho(b)['segments'] for s in g['sections'] if s['name'] == '__text')
    return b[s['fileoff']:s['fileoff'] + s['size']]


if code(obj) != code(late):
    sys.exit('Only the owned initializer registration may change')
archive = OUT / ('lib%s.late.a' % source.stem)
archive.unlink(missing_ok=True)
run(['xcrun', 'ar', 'rcs', archive, late, OUT / 'original-bindings.o'])
# The kernel links libNativeAdreno.a (or the --into archive); the staged class rides in it (its initializer is not in __mod_init_func).
native = (ROOT / options.into) if options.into else ROOT / 'build/native-adreno/libNativeAdreno.a'
if options.into and not native.is_file():
    sys.exit('No archive %s to add the staged class to' % native)
if native.exists():
    run(['xcrun', 'ar', 'rcs', native, late, OUT / 'original-bindings.o'])
(OUT / 'build-report.json').write_text(json.dumps(dict(
    source_sha256={str(p.relative_to(ROOT)): sha(p) for p in (source, ROOT / 'drivers/NativeMetal/OriginalAcceleratorABI.h')},
    archive_sha256=sha(archive), original_abi_sha256=sha(plan_path), bindings={n: hex(a) for n, a in bindings.items()},
    original_instructions_modified=False, runtime_qualified=False), indent=2) + '\n')
print('PASS: staged %s builds against the audited original IOAcceleratorES imports' % source.name)
