"""Restore a wheel's frontend from a verified, matching pgAdmin RPM extraction."""

import base64
import csv
import hashlib
import io
from pathlib import Path
import sys
import zipfile


def repair_wheel(source, web_root, output, required_assets):
    frontend = web_root / 'pgadmin/static/js/generated'
    for name in required_assets:
        path = frontend / name
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f'The donor package is missing the frontend bundle {name}')

    prefix = 'pgadmin4/pgadmin/static/js/generated/'
    with zipfile.ZipFile(source) as original:
        for name in ['version.py', 'pgadmin/templates/base.html']:
            if original.read('pgadmin4/' + name) != (web_root / name).read_bytes():
                raise ValueError(f'The Python wheel and donor package differ in {name}')
        metadata = [name for name in original.namelist() if name.endswith('.dist-info/WHEEL')]
        if len(metadata) != 1:
            raise ValueError('Expected exactly one wheel metadata directory')
        record = metadata[0].rsplit('/', 1)[0] + '/RECORD'
        rows = []

        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as repaired:
            def write(name, data, info=None):
                if info is None:
                    info = zipfile.ZipInfo(name)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                repaired.writestr(info, data)
                if not info.is_dir():
                    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=')
                    rows.append((name, 'sha256=' + digest.decode(), len(data)))

            for info in original.infolist():
                if info.filename == record or info.filename.startswith(prefix):
                    continue
                data = original.read(info)
                if info.filename == metadata[0]:
                    lines = [line for line in data.decode().splitlines() if not line.startswith('Build:')]
                    data = ('\n'.join(lines) + '\nBuild: 1\n').encode()
                write(info.filename, data, info)

            for path in sorted(frontend.rglob('*')):
                if path.is_symlink():
                    raise ValueError(f'The donor frontend contains a symlink: {path}')
                if path.is_file():
                    write(prefix + path.relative_to(frontend).as_posix(), path.read_bytes())

            rows.append((record, '', ''))
            manifest = io.StringIO(newline='')
            csv.writer(manifest).writerows(rows)
            repaired.writestr(record, manifest.getvalue())


if __name__ == '__main__':
    repair_wheel(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4:])
