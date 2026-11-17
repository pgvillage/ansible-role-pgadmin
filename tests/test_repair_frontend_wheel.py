"""Check that frontend recovery preserves code and produces an installable wheel."""

import base64
import csv
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import zipfile


spec = importlib.util.spec_from_file_location(
    'repair_frontend_wheel',
    Path(__file__).resolve().parents[1] / 'files/repair_frontend_wheel.py',
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FrontendWheelTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / 'pgadmin4-9.19-py3-none-any.whl'
        self.output = self.root / 'pgadmin4-9.19-1-py3-none-any.whl'
        self.web = self.root / 'web'
        self.frontend = self.web / 'pgadmin/static/js/generated'
        self.frontend.mkdir(parents=True)
        self.original = {
            'pgadmin4/version.py': b'APP_RELEASE = 9\nAPP_REVISION = 19\n',
            'pgadmin4/pgadmin/templates/base.html': b'<html>pgAdmin</html>',
            'pgadmin4/pgAdmin4.py': b'app = create_app()\n',
            'pgadmin4-9.19.dist-info/WHEEL': b'Wheel-Version: 1.0\nTag: py3-none-any\n',
            'pgadmin4-9.19.dist-info/METADATA': b'Name: pgadmin4\nVersion: 9.19\n',
            'pgadmin4-9.19.dist-info/RECORD': b'',
        }
        for name in ['version.py', 'pgadmin/templates/base.html']:
            destination = self.web / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(self.original['pgadmin4/' + name])
        self.assets = ['security.pages.js', 'style.css']
        for name in self.assets:
            (self.frontend / name).write_text('production bundle')
        self.write_source()

    def write_source(self):
        with zipfile.ZipFile(self.source, 'w') as archive:
            for name, data in self.original.items():
                archive.writestr(name, data)

    def repair(self):
        module.repair_wheel(self.source, self.web, self.output, self.assets)

    def test_preserves_application_code_and_records_every_file(self):
        self.repair()
        with zipfile.ZipFile(self.output) as repaired:
            for name, data in self.original.items():
                if not name.endswith(('/WHEEL', '/RECORD')):
                    self.assertEqual(repaired.read(name), data)
            record = 'pgadmin4-9.19.dist-info/RECORD'
            rows = list(csv.reader(io.StringIO(repaired.read(record).decode())))
            self.assertEqual({row[0] for row in rows}, set(repaired.namelist()))
            for name, digest, size in rows:
                if name == record:
                    self.assertEqual((digest, size), ('', ''))
                    continue
                data = repaired.read(name)
                expected = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=')
                self.assertEqual(digest, 'sha256=' + expected.decode())
                self.assertEqual(int(size), len(data))
            for name in self.assets:
                self.assertEqual(
                    repaired.read('pgadmin4/pgadmin/static/js/generated/' + name),
                    b'production bundle',
                )

    def test_rejects_mismatched_application_builds_before_writing(self):
        for name in ['version.py', 'pgadmin/templates/base.html']:
            with self.subTest(name=name):
                path = self.web / name
                original = path.read_bytes()
                path.write_bytes(b'different release')
                with self.assertRaisesRegex(ValueError, 'differ'):
                    self.repair()
                self.assertFalse(self.output.exists())
                path.write_bytes(original)

    def test_rejects_missing_or_empty_required_bundles(self):
        path = self.frontend / self.assets[0]
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.repair()
        path.touch()
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.repair()
        self.assertFalse(self.output.exists())

    def test_replaces_partial_bundles_without_duplicate_zip_entries(self):
        name = 'pgadmin4/pgadmin/static/js/generated/security.pages.js'
        self.original[name] = b'incomplete old bundle'
        self.write_source()
        self.repair()
        with zipfile.ZipFile(self.output) as repaired:
            self.assertEqual(repaired.namelist().count(name), 1)
            self.assertEqual(repaired.read(name), b'production bundle')

    def test_rejects_symlinks_in_the_frontend(self):
        (self.frontend / 'outside.js').symlink_to(self.web / 'version.py')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.repair()


if __name__ == '__main__':
    unittest.main()
