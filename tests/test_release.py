from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_release import check, source_files


class ReleaseTests(unittest.TestCase):
    def test_private_files_are_not_in_export_allowlist(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.env').write_text('secret', encoding='utf-8')
            (root / 'config.local.json').write_text('{}', encoding='utf-8')
            (root / 'data').mkdir()
            (root / 'data/material.md').write_text('private', encoding='utf-8')
            (root / 'README.md').write_text('public', encoding='utf-8')
            self.assertEqual(source_files(root), ['README.md'])
            self.assertTrue(any('unexpected' in s for s in check(root, strict=True)))

    def test_source_has_neutral_release_defaults(self):
        self.assertEqual(check(Path(__file__).resolve().parents[1]), [])
