"""仅验证已检查文件的打包与清单；夹具文件不代表真实固件。"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from apbuild import version
from assemble_release import assemble, write_checksums


class ReleaseTests(unittest.TestCase):
    def test_layout_bundles_separate_boot_files_and_have_checksums(self):
        lock = {"source_version": version(), "firmware_version": f"v{version()}-R26.10.23-b1.1", "built_at": "2026-10-23"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'README.md').write_text('中文教程')
            (root / 'boot-assets').mkdir()
            (root / 'boot-assets/来源与检查记录.json').write_text('{}')
            sources = {}
            for layout in ('stock', 'large128'):
                boot = root / 'boot-assets' / layout
                boot.mkdir()
                (boot / (layout + '-boot.bin')).write_bytes(layout.encode())
                (boot / 'README.md').write_text('初始资料说明')
                if layout == 'stock':
                    (boot / 'uboot-info.json').write_text('{"origin":"测试夹具"}')
                directory = root / layout
                directory.mkdir()
                label = 'AP-' + layout
                for suffix in ('factory.ubi', 'sysupgrade.bin', '源码.zip') + (('initramfs-uImage.itb',) if layout == 'stock' else ()):
                    (directory / (label + '-' + suffix)).write_bytes(b'packaging-fixture')
                (directory / (label + '-构建信息.json')).write_text(json.dumps({'布局标记': layout, '固件版本': lock['firmware_version']}))
                write_checksums(directory)
                sources[layout] = directory
            with patch('assemble_release.ROOT', root), patch('assemble_release.check_assets', return_value=True):
                assemble(lock, sources, root / 'release')
            for layout in sources:
                archive = next((root / 'release').glob('*-' + layout + '-完整发布包.zip'))
                with zipfile.ZipFile(archive) as stream:
                    prefix = stream.namelist()[0].split('/')[0] + '/'
                    names = stream.namelist()
                    self.assertTrue(any('/boot/' + layout + '-boot.bin' in name for name in names))
                    other = 'stock' if layout == 'large128' else 'large128'
                    self.assertFalse(any('/boot/' + other + '-boot.bin' in name for name in names))
                    for line in stream.read(prefix + 'sha256sums').decode().splitlines():
                        digest, name = line.split('  ', 1)
                        self.assertEqual(hashlib.sha256(stream.read(prefix + name)).hexdigest(), digest)
