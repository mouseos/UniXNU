import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from unixnu import kernel
from unixnu.util import Error


class Bootstrap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'kernel/kernel.macho'
        self.path.parent.mkdir()
        self.path.write_bytes(b'unknown-old-reference')
        self.path.with_suffix('.json').write_text('{}')
        self.ctx = SimpleNamespace(work=self.root, board={'kernel': {
            'source_reference_bootstrap': True, 'candidate_validator': 'check.py'}})
        self.inputs = []
        self.calls = 0

    def build(self, ctx, modules, reference_pass=None):
        self.inputs.append((reference_pass, self.path.read_bytes() if self.path.exists() else None))

    def prelink(self, ctx):
        self.calls += 1
        self.path.write_bytes(b'source-reference' if self.calls == 1 else b'final')
        self.path.with_suffix('.json').write_text('{}')
        return self.path

    def test_source_reference_and_final_validation(self):
        with patch.object(kernel, 'build', self.build), patch.object(kernel, 'prelink', self.prelink), \
             patch.object(kernel, 'validate_candidate') as validate:
            kernel.build_checked(self.ctx, {})
        self.assertEqual(self.inputs, [('bootstrap', None), ('final', b'source-reference')])
        self.assertEqual(self.path.with_name('kernel.reference.macho').read_bytes(), b'source-reference')
        validate.assert_called_once_with(self.ctx, self.path)

    def test_validator_is_mandatory(self):
        del self.ctx.board['kernel']['candidate_validator']
        with self.assertRaises(Error): kernel.build_checked(self.ctx, {})
        self.assertEqual(self.path.read_bytes(), b'unknown-old-reference')

    def test_invalid_final_propagates(self):
        with patch.object(kernel, 'build', self.build), patch.object(kernel, 'prelink', self.prelink), \
             patch.object(kernel, 'validate_candidate', side_effect=Error('stub')):
            with self.assertRaises(Error): kernel.build_checked(self.ctx, {})

    def test_unconfigured_board_uses_one_pass(self):
        self.ctx.board = {}
        with patch.object(kernel, 'build', self.build), patch.object(kernel, 'prelink', self.prelink), \
             patch.object(kernel, 'validate_candidate'):
            kernel.build_checked(self.ctx, {})
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.inputs, [(None, b'unknown-old-reference')])


if __name__ == '__main__': unittest.main()
