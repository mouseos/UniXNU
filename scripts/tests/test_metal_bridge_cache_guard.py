#!/usr/bin/env python3
"""Run the real generic builder through cache preflight, without an Apple SDK."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

source = Path(__file__).resolve().parents[1] / 'build-vulkan-metal-plugin.py'
with tempfile.TemporaryDirectory(prefix='metal-cache-guard-') as tmp:
    root = Path(tmp)
    (root / 'scripts').mkdir()
    shutil.copyfile(source, root / 'scripts/build-vulkan-metal-plugin.py')
    bridge = root / 'build/native-metal-bridge/ios/libnative_metal_bridge.a'
    bridge.parent.mkdir(parents=True)
    bridge.write_bytes(b'fixed bridge')
    driver = root / 'driver.dylib'
    driver.write_bytes(b'driver')
    board = root / 'board.mm'
    board.write_text('// fixture\n')
    out = root / 'output'
    out.mkdir()
    sentinel = out / 'existing'
    sentinel.write_text('preserve')
    digest = hashlib.sha256(bridge.read_bytes()).hexdigest()
    base = dict(target='ios', portable_sha2=True, runtime_commit_trace=True, library_sha256=digest)
    command = [sys.executable, str(root / 'scripts/build-vulkan-metal-plugin.py'), '--name', 'Fixture',
               '--principal-class', 'Device', '--vulkan-driver', str(driver), '--board-source', str(board),
               '--out', str(out), '--skip-bridge']
    for metadata, flags, expected in (
        (base, [], 'different commit trace feature'),
        ({**base, 'runtime_commit_trace': False}, ['--runtime-commit-trace'], 'different commit trace feature'),
        ({**base, 'library_sha256': '0' * 64}, ['--runtime-commit-trace'], 'metadata or digest'),
        ({**base, 'portable_sha2': False}, ['--portable-sha2', '--runtime-commit-trace'], 'not portable SHA2'),
    ):
        bridge.with_suffix('.json').write_text(json.dumps(metadata))
        result = subprocess.run(command + flags, capture_output=True, text=True)
        assert result.returncode != 0 and expected in result.stderr, result.stderr
        assert sentinel.read_text() == 'preserve'
print('PASS real builder rejects mismatched cache before replacing output')
