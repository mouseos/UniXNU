"""Exercise the real portable-cache admission branch without Xcode or a GPU."""
import ast
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


class PortableCacheTest(unittest.TestCase):
    def test_archive_bound_features(self):
        source = Path(__file__).with_name('build-vulkan-metal-plugin.py').read_text()
        tree = ast.parse(source)
        parent = next(n for n in tree.body if isinstance(n, ast.If) and
                      'args.skip_bridge' in ast.unparse(n.test))
        code = compile(ast.Module(body=parent.orelse, type_ignores=[]), '<actual cache admission>', 'exec')
        with tempfile.TemporaryDirectory(prefix='bridge-cache-test-') as tmp:
            bridge = Path(tmp) / 'libnative_metal_bridge.a'
            bridge.write_bytes(b'compiled ios archive')
            env = {'BRIDGE': bridge, 'args': SimpleNamespace(portable_sha2=True), 'json': json}
            digest = hashlib.sha256(bridge.read_bytes()).hexdigest()
            records = [None,
                       {'target': 'ios', 'portable_sha2': False, 'library_sha256': digest},
                       {'target': 'host', 'portable_sha2': True, 'library_sha256': digest},
                       {'target': 'ios', 'portable_sha2': True, 'library_sha256': 'stale'}]
            for record in records:
                if record is not None:
                    bridge.with_suffix('.json').write_text(json.dumps(record))
                with self.assertRaises(SystemExit):
                    exec(code, env)
            bridge.with_suffix('.json').write_text(json.dumps({
                'target': 'ios', 'portable_sha2': True, 'library_sha256': digest}))
            exec(code, env)
            bridge.write_bytes(b'replaced by a nonportable archive')
            with self.assertRaises(SystemExit):
                exec(code, env)


if __name__ == '__main__':
    unittest.main()
