#!/usr/bin/env python3
"""Build the vendor-neutral Metal plugin (drivers/NativeMetal/NativeVulkanMetalPlugin.mm) for ARM64/iOS 17 with one board's hooks
(drivers/NativeMetal/NativeMetalBoard.h) and that board's Vulkan driver, as an owner-signed bundle.

  build-vulkan-metal-plugin.py --name NAME --principal-class CLASS --vulkan-driver LIBRARY --board-source FILE [--board-source FILE ...]
                               [--include DIR ...] [--identifier ID] [--driver-identifier ID] [--driver-name FILE] [--out DIR]

NAME is the bundle and executable name, the accelerator's MetalPluginName; CLASS the principal class, its MetalPluginClassName.
LIBRARY (a Mesa Vulkan driver with a Darwin kernel interface; it exports vkGetInstanceProcAddr) is copied into the bundle as
--driver-name (default its own name), stripped and signed with 4 KiB pages before the bundle is sealed, so the bundle's seal covers
its final bytes; the plugin opens it beside its executable. The board sources are compiled into the executable with --include
directories (Objective-C++ for .mm, C++ for .cpp, C for .c).

Output (ignored, never committed): OUT/NAME.bundle (default OUT build/vulkan-metal-plugin/NAME) with a 4 KiB-page ad-hoc signature, and
OUT/trust.json with the CDHashes of the bundle and the driver, for an extra owner trust module (the device repository's trust bundle);
the original trust modules, AMFI and every Apple signature are unchanged. The bundle is placed beside /System/Library/Extensions by
the GPU addon union mount (patch zzy-native-gpu-addon-mount, sheng-gpu-addon=1), where the original Metal discovery looks for
MetalPluginName. scripts/build-adreno-metal-plugin.py builds the Adreno plugin; it does not use this script."""
import argparse
import json
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--name', required=True)
parser.add_argument('--principal-class', required=True)
parser.add_argument('--vulkan-driver', type=Path, required=True)
parser.add_argument('--driver-name')
parser.add_argument('--board-source', type=Path, action='append', required=True)
parser.add_argument('--include', type=Path, action='append', default=[])
parser.add_argument('--identifier', help='bundle identifier (default org.unixnu.NAME)')
parser.add_argument('--driver-identifier', help='code signing identifier of the driver (default org.unixnu.<driver stem>)')
parser.add_argument('--out', type=Path)
parser.add_argument('--skip-bridge', action='store_true', help='use the existing build/native-metal-bridge/ios/libnative_metal_bridge.a')
parser.add_argument('--portable-sha2', action='store_true', help='build the bridge without requiring CPU SHA2 instructions')
args = parser.parse_args()

name_ok = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
if not name_ok.match(args.name) or not name_ok.match(args.principal_class):
    raise SystemExit('--name and --principal-class must be plain identifiers')
driver = args.vulkan_driver.resolve()
if not driver.is_file():
    raise SystemExit('No Vulkan driver at %s' % driver)
driver_name = args.driver_name or driver.name
if '/' in driver_name or not driver_name.endswith('.dylib'):
    raise SystemExit('--driver-name is a file name ending in .dylib')
sources = [s.resolve() for s in args.board_source]
for source in sources:
    if not source.is_file() or source.suffix not in ('.mm', '.cpp', '.c'):
        raise SystemExit('Board source %s: not a .mm, .cpp or .c file' % source)
identifier = args.identifier or 'org.unixnu.' + args.name
driver_identifier = args.driver_identifier or 'org.unixnu.' + Path(driver_name).stem

OUT = (args.out or ROOT / 'build/vulkan-metal-plugin' / args.name).resolve()
if OUT.exists():
    shutil.rmtree(OUT)
bundle = OUT / (args.name + '.bundle')
bundle.mkdir(parents=True)
BRIDGE = ROOT / 'build/native-metal-bridge/ios/libnative_metal_bridge.a'
if not (args.skip_bridge and BRIDGE.is_file()):
    subprocess.run(['python3', ROOT / 'scripts/build-native-metal-bridge.py', '--target', 'ios'] +
                   (['--portable-sha2'] if args.portable_sha2 else []), check=True)
elif args.portable_sha2:
    import hashlib
    record = BRIDGE.with_suffix('.json')
    metadata = json.loads(record.read_text()) if record.is_file() else {}
    with BRIDGE.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if metadata.get('target') != 'ios' or metadata.get('portable_sha2') is not True or metadata.get('library_sha256') != digest:
        raise SystemExit('Existing bridge is not portable SHA2; rebuild without --skip-bridge')
sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
base = ['-target', 'arm64-apple-ios17.0', '-isysroot', sdk, '-O2', '-g', '-Wall', '-Wextra', '-Werror', '-fstack-protector-strong']
includes = ['-I', str(ROOT / 'drivers/NativeMetal')]
for directory in args.include:
    includes += ['-I', str(directory.resolve())]
defines = ['-DNATIVE_METAL_PLUGIN_CLASS=' + args.principal_class, '-DNATIVE_METAL_VULKAN_DRIVER="%s"' % driver_name]
objects = []
for source in [ROOT / 'drivers/NativeMetal/NativeVulkanMetalPlugin.mm', ROOT / 'drivers/NativeMetal/NativeBridgeMetalFrontend.mm', *sources]:
    obj = OUT / (source.stem + '.o')
    if source.suffix == '.mm':
        language = ['xcrun', 'clang++', '-std=c++17', '-x', 'objective-c++', '-fobjc-arc', '-Wno-deprecated-declarations']
    elif source.suffix == '.cpp':
        language = ['xcrun', 'clang++', '-std=c++17', '-x', 'c++']
    else:
        language = ['xcrun', 'clang', '-std=gnu11', '-x', 'c']
    subprocess.run([*language, *base, *includes, *defines, '-c', str(source), '-o', str(obj)], check=True)
    objects.append(obj)
exe = bundle / args.name
subprocess.run(['xcrun', 'clang++', *base, '-bundle', *map(str, objects), str(BRIDGE), '-Wl,-dead_strip', '-lobjc',
                '-framework', 'Foundation', '-framework', 'Metal', '-framework', 'IOSurface', '-o', str(exe)], check=True)
subprocess.run(['strip', '-x', str(exe)], check=True)
symbols = bundle / (args.name + '.dSYM')
if symbols.exists():
    shutil.move(symbols, OUT / symbols.name)
header = exe.read_bytes()[:16]
magic, cputype, subtype = (int.from_bytes(header[i:i + 4], 'little') for i in (0, 4, 8))
assert (magic, cputype, subtype & 0xffffff) == (0xfeedfacf, 0x100000c, 0), 'expected an ordinary ARM64 (subtype 0) Mach-O'


def sign(path, ident):
    subprocess.run(['codesign', '--force', '--sign', '-', '--pagesize', '4096', '--identifier', ident, str(path)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(path)], check=True)
    detail = subprocess.run(['codesign', '--display', '--verbose=4', str(path)], capture_output=True, text=True, check=True).stderr
    if not re.search(r'^Page size=4096$', detail, re.M):
        raise SystemExit('%s: the signature must use 4 KiB pages' % path)
    return re.search(r'^CDHash=([a-f0-9]{40})$', detail, re.M)[1]


# The driver first, so that the bundle's resource seal covers its final bytes.
staged = bundle / driver_name
shutil.copyfile(driver, staged)
subprocess.run(['strip', '-x', str(staged)], check=True)
driver_cdhash = sign(staged, driver_identifier)
(bundle / 'Info.plist').write_bytes(plistlib.dumps(dict(
    CFBundleIdentifier=identifier, CFBundleExecutable=args.name, CFBundlePackageType='BNDL', CFBundleVersion='1',
    CFBundleShortVersionString='1', NSPrincipalClass=args.principal_class, MinimumOSVersion='17.0'), fmt=plistlib.FMT_XML))
cdhash = sign(bundle, identifier)
(OUT / 'trust.json').write_text(json.dumps(dict(
    bundle=bundle.name, cdhash=cdhash, driver=driver_name, driver_cdhash=driver_cdhash, executable_bytes=exe.stat().st_size,
    principal_class=args.principal_class, purpose='owner-built Metal plugin and Vulkan driver; trusted only through an extra owner trust module'),
    indent=2) + '\n')
print('PASS: %s built and 4K-signed, CDHashes %s %s' % (bundle.name, cdhash, driver_cdhash))
