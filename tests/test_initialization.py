"""使用真实 OpenWrt UCI，在隔离目录中执行出厂初始化脚本。"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from apbuild import ROOT, read_json, version
from configure_profile import build_profile
from prepare import generate_package

NATIVE = os.environ.get("AP8220_NATIVE_UCI")


@unittest.skipUnless(NATIVE, "需要 AP8220_NATIVE_UCI 指定真实 UCI，CI 会自动构建")
class InitializationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        tree = self.base / "tree"
        lock = {
            "source_version": version(), "firmware_version": f"v{version()}-R26.10.23-b1.1",
            "lean": {"commit": "a" * 40}, "build_commit": "b" * 40,
            "built_at": "2026-10-23T08:00:00+08:00",
        }
        self.lock = lock
        generate_package(tree, lock, read_json(ROOT / "config/ap-defaults.json"))
        self.root = tree / "package/custom/ap8220-ap-defaults/files"
        for name in ("tmp/sysinfo", "sys/class/net/lan", "tmp/.uci"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.root / "tmp/sysinfo/board_name").write_text("aliyun,ap8220\n")
        (self.root / "sys/class/net/lan/address").write_text("02:11:22:33:44:55\n")
        (self.root / "proc").mkdir()
        (self.root / "dev").mkdir()
        (self.root / "proc/mtd").write_text('mtd12: 00010000 00010000 "product_info"\n')
        self.product_info = self.root / "dev/mtd12"
        self.product_info.write_bytes(b'product.model=AP8220\x00product.mac=00:11:22:33:44:54\x00')
        (self.root / "etc/config/system").write_text(
            "config system\n option hostname 'OpenWrt'\n"
            "config timeserver 'ntp'\n option enable_server '1'\n"
        )
        (self.root / "etc/config/luci").write_text("config core 'main'\n option lang 'auto'\n")
        (self.root / "etc/config/network").write_text(
            "config interface 'lan'\n option proto 'static'\n option ipaddr '192.168.1.1'\n"
            "config interface 'wan'\n option proto 'dhcp'\n"
        )
        (self.root / "etc/shadow").write_text("root::0:0:99999:7:::\nnobody:*:0:0:99999:7:::\n")
        self.wireless()
        self.env = dict(os.environ, AP8220_TEST_ROOT=str(self.root), AP8220_TEST_MODE="1", AP8220_UCI_BIN=NATIVE)

    def tearDown(self):
        self.temporary.cleanup()

    def wireless(self, include_2g=True):
        # 故意令 radio0=5GHz、radio1=2.4GHz，验证不依赖编号。
        text = (
            "config wifi-device 'radio0'\n option type 'mac80211'\n option band '5g'\n"
            " option path 'platform/test/5g'\n option disabled '1'\n"
            "config wifi-iface 'old'\n option device 'radio0'\n option ssid 'OpenWrt'\n"
        )
        if include_2g:
            text += "config wifi-device 'radio1'\n option type 'mac80211'\n option band '2g'\n option path 'platform/test/2g'\n"
        (self.root / "etc/config/wireless").write_text(text)

    def uci(self, *args):
        return subprocess.run(
            [NATIVE, "-c", str(self.root / "etc/config"), "-t", str(self.root / "tmp/.uci"), *args],
            text=True, capture_output=True, check=True,
        ).stdout.strip()

    def initialize(self):
        return subprocess.run(
            ["sh", str(self.root / "usr/sbin/ap8220-ap-initialize")],
            env=self.env, text=True, capture_output=True,
        )

    def test_bridge_dhcp_and_radio_mapping(self):
        result = self.initialize()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.uci("get", "network.br_lan.ports"), "lan wan")
        self.assertEqual(self.uci("get", "network.lan.proto"), "dhcp")
        self.assertEqual(self.uci("get", "network.lan6.reqprefix"), "no")
        self.assertEqual(self.uci("get", "wireless.ap5g.device"), "radio0")
        self.assertEqual(self.uci("get", "wireless.ap2g.device"), "radio1")
        self.assertEqual(self.uci("get", "wireless.ap2g.ssid"), "Home-WiFi")
        self.assertEqual(self.uci("get", "wireless.ap5g.ssid"), "Home-WiFi")
        self.assertEqual(self.uci("get", "wireless.radio1.channel"), "1")
        self.assertEqual(self.uci("get", "wireless.radio0.channel"), "36")
        self.assertEqual(self.uci("get", "wireless.ap2g.mobility_domain"), "a1b2")
        self.assertEqual(self.uci("get", "wireless.ap5g.mobility_domain"), "a1b2")
        self.assertEqual(self.uci("get", "wireless.ap5g.nasid"), "001122334455-5g")
        self.assertEqual(self.uci("get", "network.br_lan.macaddr"), "00:11:22:33:44:55")
        self.assertEqual(self.uci("get", "network.ap8220_port_wan.macaddr"), "00:11:22:33:44:54")
        self.assertEqual(self.uci("get", "luci.main.mediaurlbase"), "/luci-static/footstrap")
        self.assertEqual(self.uci("get", "wireless.ap2g.key"), "12345678")
        self.assertEqual(self.uci("get", "turboacc.config.fastpath"), "qca_nss_ecm")
        self.assertEqual(self.uci("get", "dhcp.lan.ignore"), "1")
        self.assertEqual(self.uci("get", "usteer.main.aggressiveness"), "1")
        self.assertEqual(self.uci("get", "usteer.main.ssid_list"), "Home-WiFi")
        self.assertNotIn("config interface 'wan'", (self.root / "etc/config/network").read_text())
        self.assertTrue((self.root / "etc/shadow").read_text().startswith("root:$6$"))
        self.assertEqual(self.uci("get", "ap8220_ap.core.initialized"), "1")

    def test_build_parameters_reach_both_radios_and_root_password(self):
        # 重建另一棵仅用于读取 defaults.conf 的目录，模拟本次不同输入。
        tree = self.base / "custom-profile"
        profile = build_profile(read_json(ROOT / "config/ap-defaults.json"), {
            "WIFI_SSID": "Home-Second", "WIFI_SSID_5G": "Home-Second_5G", "WIFI_KEY": "Custom-WiFi-98765",
            "ROOT_PASSWORD": "Custom-Root-98765", "CHANNEL_2G": "11", "CHANNEL_5G": "149",
            "MOBILITY_DOMAIN": "abcd",
        })
        generate_package(tree, self.lock, profile)
        defaults = Path("usr/share/ap8220-ap/defaults.conf")
        shutil.copy2(tree / "package/custom/ap8220-ap-defaults/files" / defaults, self.root / defaults)
        result = self.initialize()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        for name, ssid in (("ap2g", "Home-Second"), ("ap5g", "Home-Second_5G")):
            self.assertEqual(self.uci("get", f"wireless.{name}.ssid"), ssid)
            self.assertEqual(self.uci("get", f"wireless.{name}.key"), "Custom-WiFi-98765")
            self.assertEqual(self.uci("get", f"wireless.{name}.mobility_domain"), "abcd")
        self.assertEqual(self.uci("get", "wireless.radio1.channel"), "11")
        self.assertEqual(self.uci("get", "wireless.radio0.channel"), "149")
        self.assertEqual(self.uci("get", "usteer.main.ssid_list"), "Home-Second Home-Second_5G")
        actual_hash = (self.root / "etc/shadow").read_text().splitlines()[0].split(":")[1]
        expected = subprocess.run(["openssl", "passwd", "-6", "-salt", actual_hash.split("$")[2], "-stdin"], input=profile["root_password"] + "\n", text=True, capture_output=True, check=True).stdout.strip()
        self.assertEqual(actual_hash, expected)

    def test_existing_configuration_is_not_overwritten(self):
        self.assertEqual(self.initialize().returncode, 0)
        self.uci("set", "network.lan.proto=static")
        self.uci("set", "network.lan.ipaddr=192.168.10.8")
        self.uci("set", "wireless.ap5g.ssid=用户修改的无线")
        self.uci("commit")
        before = {name: (self.root / "etc/config" / name).read_bytes() for name in ("network", "wireless", "usteer", "turboacc")}
        password = (self.root / "etc/shadow").read_bytes()
        self.assertEqual(self.initialize().returncode, 0)
        for name, content in before.items():
            self.assertEqual((self.root / "etc/config" / name).read_bytes(), content)
        self.assertEqual((self.root / "etc/shadow").read_bytes(), password)

    def test_delayed_wireless_does_not_reset_completed_base(self):
        self.wireless(include_2g=False)
        self.assertEqual(self.initialize().returncode, 1)
        self.assertEqual(self.uci("get", "network.lan.proto"), "dhcp")
        self.assertEqual(self.uci("get", "ap8220_ap.core.base_configured"), "1")
        before = (self.root / "etc/shadow").read_bytes()
        self.wireless()
        self.assertEqual(self.initialize().returncode, 0)
        self.assertEqual((self.root / "etc/shadow").read_bytes(), before)

    def test_device_identity_comes_from_mac(self):
        self.assertEqual(self.initialize().returncode, 0)
        self.assertEqual(self.uci("get", "system.@system[0].hostname"), "AP8220-334455")

    def test_wrong_device_is_rejected(self):
        (self.root / "tmp/sysinfo/board_name").write_text("other,device")
        before = (self.root / "etc/config/network").read_bytes()
        self.assertNotEqual(self.initialize().returncode, 0)
        self.assertEqual((self.root / "etc/config/network").read_bytes(), before)

    def test_invalid_mac_is_rejected(self):
        self.product_info.write_bytes(b'product.mac=00:00:00:00:00:00\x00')
        self.assertNotEqual(self.initialize().returncode, 0)
        self.assertEqual((self.root / "etc/shadow").read_text().splitlines()[0], "root::0:0:99999:7:::")

    def test_factory_mac_is_required_despite_valid_random_interface(self):
        self.product_info.unlink()
        self.assertNotEqual(self.initialize().returncode, 0)
        self.assertEqual(self.uci('get', 'network.lan.proto'), 'static')

    def test_invalid_or_duplicate_factory_macs_are_rejected(self):
        for value in (b'ff:ff:ff:ff:ff:ff', b'01:11:22:33:44:54', b'001122334454\x00product.mac=001122334455'):
            self.product_info.write_bytes(b'product.mac=' + value + b'\x00')
            self.assertNotEqual(self.initialize().returncode, 0)

    def test_factory_identity_survives_runtime_mac_changes_and_nic_wrap(self):
        self.product_info.write_bytes(b'product.mac=00-11-22-FF-FF-FF\x00')
        self.assertEqual(self.initialize().returncode, 0)
        self.assertEqual(self.uci('get', 'network.br_lan.macaddr'), '00:11:22:00:00:00')
        (self.root / 'sys/class/net/lan/address').write_text('a2:93:6f:50:4d:2f')
        self.assertEqual(self.initialize().returncode, 0)
        self.assertEqual(self.uci('get', 'ap8220_ap.core.base_mac'), '00:11:22:00:00:00')

    def old_identity(self):
        self.assertEqual(self.initialize().returncode, 0)
        self.uci('delete', 'ap8220_ap.core.identity_schema')
        self.uci('set', 'ap8220_ap.core.base_mac=a2:93:6f:50:4d:2f')
        self.uci('set', 'network.br_lan.macaddr=a2:93:6f:50:4d:2f')
        self.uci('delete', 'network.ap8220_port_lan')
        self.uci('delete', 'network.ap8220_port_wan')
        self.uci('set', 'system.@system[0].hostname=AP8220-504D2F')
        self.uci('set', 'network.lan.hostname=AP8220-504D2F')
        for band in ('2g','5g'):
            self.uci('set', f'wireless.ap{band}.nasid=a2936f504d2f-{band}')
        self.uci('set', 'wireless.ap5g.ssid=用户保留的无线')
        self.uci('set', 'network.lan.proto=static')
        self.uci('set', 'network.lan.ipaddr=192.168.10.8')
        self.uci('set', 'luci.main.mediaurlbase=/luci-static/argon')
        self.uci('commit')

    def migrate(self):
        return subprocess.run(['sh',str(self.root/'usr/sbin/ap8220-ap-migrate')],env=self.env,text=True,capture_output=True)

    def test_upgrade_migrates_only_automatic_identity(self):
        self.old_identity()
        before = (self.root/'etc/shadow').read_bytes()
        result = self.migrate()
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertEqual(self.uci('get','network.br_lan.macaddr'),'00:11:22:33:44:55')
        self.assertEqual(self.uci('get','system.@system[0].hostname'),'AP8220-334455')
        self.assertEqual(self.uci('get','wireless.ap5g.nasid'),'001122334455-5g')
        self.assertEqual(self.uci('get','wireless.ap5g.ssid'),'用户保留的无线')
        self.assertEqual(self.uci('get','network.lan.ipaddr'),'192.168.10.8')
        self.assertEqual(self.uci('get','network.lan.proto'),'static')
        self.assertEqual(self.uci('get','luci.main.mediaurlbase'),'/luci-static/argon')
        self.assertEqual((self.root/'etc/shadow').read_bytes(),before)
        backup=self.root/'etc/ap8220-identity-backup/network'
        self.assertIn(b'a2:93:6f:50:4d:2f',backup.read_bytes())
        after=(self.root/'etc/config/network').read_bytes()
        self.assertEqual(self.migrate().returncode,0)
        self.assertEqual((self.root/'etc/config/network').read_bytes(),after)

    def test_migration_preserves_custom_bridge_hostname_and_nas(self):
        self.old_identity()
        self.uci('set','network.br_lan.macaddr=02:aa:bb:cc:dd:ee');self.uci('commit')
        before=(self.root/'etc/config/network').read_bytes()
        self.assertEqual(self.migrate().returncode,0)
        self.assertEqual((self.root/'etc/config/network').read_bytes(),before)
        self.uci('set','network.br_lan.macaddr=a2:93:6f:50:4d:2f')
        self.uci('set','system.@system[0].hostname=My-AP')
        self.uci('set','wireless.ap5g.nasid=my-custom-nas');self.uci('commit')
        self.assertEqual(self.migrate().returncode,0)
        self.assertEqual(self.uci('get','system.@system[0].hostname'),'My-AP')
        self.assertEqual(self.uci('get','wireless.ap5g.nasid'),'my-custom-nas')

    def test_failed_migration_preserves_all_configuration(self):
        self.old_identity(); self.product_info.unlink()
        before={p:p.read_bytes() for p in (self.root/'etc/config').iterdir() if p.is_file()}
        self.assertNotEqual(self.migrate().returncode,0)
        self.assertTrue(all(p.read_bytes()==value for p,value in before.items()))
