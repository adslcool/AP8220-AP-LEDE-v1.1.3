"""双布局的结构、容量、启动文件和升级拒绝行为。"""
from pathlib import Path
import shutil
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from apbuild import ROOT
from boot_assets import check_assets
from images import validate_ap8220_fit
from layouts import adapt_dts, adapt_image_makefile, adapt_platform, adapt_envtools
from test_images import ap_nodes, fit


class LayoutTests(unittest.TestCase):
    def test_stock_and_large_fit_are_distinct(self):
        nodes = ap_nodes()
        nodes["/"]["ap8220,flash-layout"] = b"stock\0"
        base = "/soc/nand-controller/nand@0/partitions/"
        del nodes[base + "partition@0"]
        for name, offset, size in (("rootfs1", 0, 0x3000000), ("rootfs2", 0x3000000, 0x3000000), ("usrdata", 0x6000000, 0x2000000)):
            nodes[base + f"partition@{offset:x}"] = {"label": name.encode() + b"\0", "reg": struct.pack(">II", offset, size)}
        validate_ap8220_fit(fit(nodes), "stock", True)
        with self.assertRaises(ValueError):
            validate_ap8220_fit(fit(nodes), "large128", True)
        nodes[base + "partition@6000000"]["reg"] = struct.pack(">II", 0x6000000, 0x3000000)
        with self.assertRaises(ValueError):
            validate_ap8220_fit(fit(nodes), "stock", True)

    def test_new_delivery_requires_explicit_layout_marker(self):
        with self.assertRaises(ValueError):
            validate_ap8220_fit(fit(ap_nodes()), "large128", True)

    def test_dts_only_changes_layout_and_marker(self):
        text = '/ { model = "Aliyun AP8220"; };\nnand@0 { partitions { partition@0 { label = "rootfs"; reg = <0x0 0x0>; }; }; };\n&noise { status = "okay"; };\n'
        stock = adapt_dts(text, "stock")
        self.assertIn('label = "rootfs1";', stock)
        self.assertIn('reg = <0x6000000 0x2000000>;', stock)
        self.assertTrue(stock.endswith('&noise { status = "okay"; };\n'))
        self.assertIn('ap8220,flash-layout = "large128";', adapt_dts(text, "large128"))
        with self.assertRaises(ValueError):
            adapt_dts(stock, "stock")

    def test_image_metadata_is_layout_specific(self):
        text = 'define Device/aliyun_ap8220\n\tSOC := ipq8071\nendef\n'
        self.assertIn('IMAGE_METADATA := "ap8220_layout": "stock"', adapt_image_makefile(text, "stock"))
        with self.assertRaises(ValueError):
            adapt_image_makefile(text.replace('aliyun_ap8220', 'other'), "stock")

    def test_platform_checks_before_nand_upgrade(self):
        text = 'platform_check_image() {\n\treturn 0;\n}\nplatform_do_upgrade() {\ncase "$(board_name)" in\naliyun,ap8220|\\\nother) nand_do_upgrade "$1" ;;\nesac\n}\nRAMFS_COPY_BIN=""\nRAMFS_COPY_DATA=""\n'
        rendered = adapt_platform(text)
        self.assertIn('ap8220_do_upgrade "$1"', rendered)
        self.assertIn('/lib/upgrade/ap8220-layout.sh', rendered)
        subprocess.run(['sh', '-n'], input=rendered, text=True, check=True)

    def test_envtools_adds_correct_spi_environment_geometry(self):
        text = 'case "$board" in\ncompex,wpq873|\\\nedgecore,eap102)\n ub oot\n ubootenv_add_uci_config "/dev/mtd$idx" "0x0" "0x10000" "0x10000" "1"\n ;;\nesac\n'
        self.assertIn('aliyun,ap8220|\\\ncompex', adapt_envtools(text))
        with self.assertRaises(ValueError):
            adapt_envtools(text.replace('0x10000', '0x20000'))

    def test_missing_original_uboot_stops_complete_release(self):
        # 独立夹具：不因后来补齐仓库原厂备份而改变测试含义。
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "assets"
            shutil.copytree(ROOT / "boot-assets", root)
            for name in ("ap8220-stock-uboot.bin", "uboot-info.json"):
                (root / "stock" / name).unlink(missing_ok=True)
            self.assertFalse(check_assets(root=root))
            with self.assertRaises(ValueError):
                check_assets(True, root)

    def test_supplied_original_uboot_completes_real_assets(self):
        self.assertTrue(check_assets(True))

    def test_altered_mibib_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "assets"
            shutil.copytree(ROOT / "boot-assets", root)
            path = root / "large128/ap8220-large128-mibib.bin"
            data = bytearray(path.read_bytes()); data[500] ^= 1; path.write_bytes(data)
            with self.assertRaises(ValueError):
                check_assets(root=root)

    def test_upgrade_refuses_mismatch_and_selects_current_stock_slot(self):
        source = (ROOT / "package/ap8220-ap-defaults/files/lib/upgrade/ap8220-layout.sh").read_text()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release = root / "release"
            release.write_text('FLASH_LAYOUT=stock\n')
            source = source.replace('/etc/ap8220-ap-release', str(release))
            wrappers = '''
ap8220_current_layout() { echo stock; }
fwtool() { printf '{"ap8220_layout":"stock"}' > "$3"; }
jsonfilter() { echo stock; }
fw_printenv() { echo 2; }
nand_do_upgrade() { echo "WRITE:$CI_UBIPART"; }
'''
            result = subprocess.run(['sh'], input=source + wrappers + '\nap8220_do_upgrade image.bin\n', text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('WRITE:rootfs2', result.stdout)
            result = subprocess.run(['sh'], input=source + wrappers + '\njsonfilter() { echo large128; }\nap8220_do_upgrade image.bin\n', text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('WRITE:', result.stdout)
            result = subprocess.run(['sh'], input=source + wrappers + '\nfw_printenv() { echo invalid; }\nap8220_do_upgrade image.bin\n', text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('WRITE:', result.stdout)

    def test_current_layout_is_detected_from_exact_mtd_sizes(self):
        source = (ROOT / "package/ap8220-ap-defaults/files/lib/upgrade/ap8220-layout.sh").read_text()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mtd"
            program = source.replace('/proc/mtd', str(path)) + '\nap8220_current_layout\n'
            cases = (
                ('mtd14: 08000000 00020000 "rootfs"\n', 'large128'),
                ('mtd14: 03000000 00020000 "rootfs1"\nmtd15: 03000000 00020000 "rootfs2"\nmtd16: 02000000 00020000 "usrdata"\n', 'stock'),
                ('mtd14: 10000000 00020000 "rootfs"\n', ''),
            )
            for contents, expected in cases:
                path.write_text(contents)
                result = subprocess.run(['sh'], input=program, text=True, capture_output=True, check=True)
                self.assertEqual(result.stdout.strip(), expected)

    def test_failed_environment_read_never_reaches_flash(self):
        source = (ROOT / "package/ap8220-ap-defaults/files/lib/upgrade/ap8220-layout.sh").read_text()
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary) / 'release'
            release.write_text('FLASH_LAYOUT=stock\n')
            source = source.replace('/etc/ap8220-ap-release', str(release))
            wrappers = '''
ap8220_current_layout() { echo stock; }
fwtool() { printf '{"ap8220_layout":"stock"}' > "$3"; }
jsonfilter() { echo stock; }
fw_printenv() { echo 2; return 1; }
nand_do_upgrade() { echo "WRITE:$CI_UBIPART"; }
'''
            for command in ('ap8220_check_layout image.bin', 'ap8220_do_upgrade image.bin'):
                result = subprocess.run(['sh'], input=source + wrappers + '\n' + command + '\n', text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('无法可靠读取', result.stderr)
                self.assertNotIn('WRITE:', result.stdout)

    def test_upgrade_runs_with_only_declared_ramfs_commands(self):
        # 模拟 stage2 切换根目录：PATH 只留下通用命令和平台明确复制的命令。
        platform = '''RAMFS_COPY_BIN='fw_printenv fw_setenv head'
RAMFS_COPY_DATA=''
platform_check_image() {
\treturn 0;
}
platform_do_upgrade() {
case "$(board_name)" in
aliyun,ap8220|\\
other) nand_do_upgrade "$1" ;;
esac
}
'''
        rendered = adapt_platform(platform).replace('. /lib/upgrade/ap8220-layout.sh', ':')
        copied = subprocess.run(['sh'], input=rendered + '\nprintf "%s" "$RAMFS_COPY_BIN"\n', text=True, capture_output=True, check=True).stdout.split()
        source = (ROOT / "package/ap8220-ap-defaults/files/lib/upgrade/ap8220-layout.sh").read_text()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commands = root / 'bin'
            commands.mkdir()
            # 本组命令来自上游 stage2 的通用复制清单，不含平台补充命令。
            for command in set(['awk', 'sed', 'rm'] + copied):
                binary = shutil.which(command)
                if binary:
                    (commands / command).symlink_to(binary)
            release = root / 'release'
            mtd = root / 'mtd'
            source = source.replace('/etc/ap8220-ap-release', str(release)).replace('/proc/mtd', str(mtd))
            wrappers = '''
fwtool() { printf '{"ap8220_layout":"%s"}' "$TEST_LAYOUT" > "$3"; }
jsonfilter() { echo "$TEST_LAYOUT"; }
fw_printenv() { echo 1; }
nand_do_upgrade() { echo "WRITE:$CI_UBIPART"; }
'''
            for layout, contents, partition in (
                ('stock', 'mtd14: 03000000 00020000 "rootfs1"\nmtd15: 03000000 00020000 "rootfs2"\nmtd16: 02000000 00020000 "usrdata"\n', 'rootfs1'),
                ('large128', 'mtd14: 08000000 00020000 "rootfs"\n', 'rootfs'),
            ):
                release.write_text('FLASH_LAYOUT=' + layout + '\n')
                mtd.write_text(contents)
                environment = dict(os.environ, PATH=str(commands), TEST_LAYOUT=layout)
                result = subprocess.run(['/bin/sh'], input=source + wrappers + '\nap8220_do_upgrade image.bin\n', text=True, capture_output=True, env=environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('WRITE:' + partition, result.stdout)

    def test_workflow_checks_completeness_before_expensive_build(self):
        import yaml
        data = yaml.load((ROOT / '.github/workflows/编译发布.yml').read_text(), Loader=yaml.BaseLoader)
        steps = data['jobs']['build']['steps']
        preflight = next(i for i, step in enumerate(steps) if '--require-complete' in step.get('run', ''))
        build = next(i for i, step in enumerate(steps) if 'build_variants.py' in step.get('run', ''))
        self.assertLess(preflight, build)
        self.assertIn('inputs.publish', steps[preflight]['if'])
        self.assertIn('--profile work/ap-profile.json', steps[build]['run'])
