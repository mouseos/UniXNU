"""Exercise the real build controller's environment across both output layouts."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import os
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unixnu import kernel
from unixnu.util import Error

class OutputRootTest(unittest.TestCase):
    def test_cli_root_reaches_archives_and_link(self):
        for schema in (1, 2):
            with self.subTest(schema=schema), tempfile.TemporaryDirectory() as directory:
                out = Path(directory) / 'custom output'
                work = out / 'a04br3'
                if schema == 2:
                    work /= 'ipados-17.7.11-21H461/a04br3'
                tree = work / 'tree'
                (tree / 'scripts').mkdir(parents=True)
                (tree / 'scripts/build-xnu-schema1-baseline.sh').touch()
                record = tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT/startup.o.json'
                record.parent.mkdir(parents=True)
                record.touch()
                ctx = SimpleNamespace(schema_version=schema, board={'kernel': {'build_script': 'build-xnu-schema1-baseline.sh'}},
                                      tree=tree, out_root=out, jobs=2, logs=work/'logs')
                seen = []
                with patch.dict(os.environ, {'UNIXNU_OUT': '/wrong/inherited'}), \
                     patch.object(kernel.platform, 'system', return_value='Darwin'), \
                     patch.object(kernel, 'tool'), patch.object(kernel, 'xnu_env', return_value={}), \
                     patch.object(kernel, 'version_env', return_value={}), \
                     patch.object(kernel.patches, 'prepare', return_value=work/'patch-list'), \
                     patch.object(kernel, 'build_archives', side_effect=lambda c,e: seen.append(e['UNIXNU_OUT'])), \
                     patch.object(kernel, 'run', side_effect=lambda *a,**k: seen.append(k['env']['UNIXNU_OUT'])):
                    kernel.build(ctx, {})
                    self.assertEqual(os.environ['UNIXNU_OUT'], '/wrong/inherited')
                self.assertEqual(seen, [str(out), str(out)])

    def test_bootstrap_requires_record_before_archive_build(self):
        for produces_record in (False, True):
            with self.subTest(produces_record=produces_record), tempfile.TemporaryDirectory() as directory:
                out = Path(directory)/'output'
                tree = out/'board/os/config/tree'
                (tree/'scripts').mkdir(parents=True)
                (tree/'scripts/build-xnu-schema1-baseline.sh').touch()
                record = tree/'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT/startup.o.json'
                ctx = SimpleNamespace(schema_version=2, board={'kernel': {'build_script':'build-xnu-schema1-baseline.sh'}},
                                      tree=tree, out_root=out, jobs=2, logs=tree.parent/'logs')
                calls=[]
                def run(command, **kwargs):
                    env=kwargs['env']
                    self.assertEqual(env['UNIXNU_OUT'], str(out))
                    calls.append('bootstrap' if env.get('XNU_BOOTSTRAP') == '1' else 'link')
                    if calls[-1]=='bootstrap':
                        if produces_record:
                            record.parent.mkdir(parents=True)
                            record.touch()
                        raise Error('fixture bootstrap stops at link')
                with patch.object(kernel.platform, 'system', return_value='Darwin'), \
                     patch.object(kernel, 'tool'), patch.object(kernel, 'xnu_env', return_value={}), \
                     patch.object(kernel, 'version_env', return_value={}), \
                     patch.object(kernel.patches, 'prepare', return_value=out/'patch-list'), \
                     patch.object(kernel, 'build_archives', side_effect=lambda *args: calls.append('archives')), \
                     patch.object(kernel, 'run', side_effect=run):
                    if produces_record:
                        kernel.build(ctx, {})
                        self.assertEqual(calls,['bootstrap','archives','link'])
                    else:
                        with self.assertRaises(Error):
                            kernel.build(ctx, {})
                        self.assertEqual(calls,['bootstrap'])

if __name__ == '__main__':
    unittest.main()
