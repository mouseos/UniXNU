#!/usr/bin/env python3
"""Exercise the real build-script header/stamp logic across Data seed changes."""
from pathlib import Path
import os
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / 'build-xnu-4k-baseline.sh').read_text()
fragment = source[source.index('OWNER_DATA_HEADER=$ROOT/'):source.index('\nOWNER_CRYPTEX_FILES=', source.index('OWNER_DATA_HEADER=$ROOT/'))]
old = 'CBB0DD3D-2FAC-4AC9-9C16-1D0F7D15CE36'
new = 'D13CBA9C-6FDF-4945-8A60-94B197C4071C'
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    obj = root / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/bsd/DEVELOPMENT/kern_exec.o'
    obj.parent.mkdir(parents=True)
    env = dict(os.environ, ROOT=temp, OWNER_DATA_MOUNT='1', NATIVE_RAM_BLOCK='1', XNU_OWNER_DATA_VOLUME_UUID=old)
    def run():
        subprocess.run(['bash', '-eu', '-c', fragment], env=env, check=True)
    run()
    obj.touch()
    run()
    assert obj.exists(), 'unchanged identity must preserve incremental object'
    env['XNU_OWNER_DATA_VOLUME_UUID'] = new
    run()
    assert not obj.exists(), 'changed Data UUID must invalidate kern_exec.o'
    assert new in (root / 'build/xnu/owner-data-volume.h').read_text()
    obj.touch()
    env['XNU_OWNER_CACHE_VOLUME_UUID'] = '8846FE78-2910-4297-AF97-D59BB6F8FC16'
    run()
    assert obj.exists(), 'equivalent default cache UUID must preserve object'
    env['XNU_OWNER_CACHE_VOLUME_UUID'] = '12345678-1234-5678-9ABC-123456789ABC'
    run()
    assert not obj.exists(), 'changed cache UUID must invalidate kern_exec.o'
print('PASS: Data and cache UUID changes invalidate kern_exec.o')
