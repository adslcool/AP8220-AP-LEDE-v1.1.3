"""验证编译参数进入实际配置，密码不进入公开交付参数。"""
import contextlib
import io
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from apbuild import ROOT, read_json, version
from collect import check_built_profile, shell_values, source_zip
from configure_profile import build_profile, mask_password, public_profile, write_private_profile
from prepare import generate_package


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.base = read_json(ROOT / "config/ap-defaults.json")

    def test_defaults_match_requested_profile(self):
        profile = build_profile(self.base, {})
        self.assertEqual((profile["ssid_2g"], profile["ssid_5g"]), ("Home-WiFi", "Home-WiFi"))
        self.assertEqual((profile["channel_2g"], profile["channel_5g"]), ("1", "36"))
        self.assertEqual(profile["mobility_domain_2g"], "a1b2")
        self.assertEqual(profile["root_password"], "password")

    def test_second_ap_and_separate_ssid(self):
        profile = build_profile(self.base, {"WIFI_SSID": "客厅 Wi-Fi", "WIFI_SSID_5G": "客厅_5G", "CHANNEL_2G": "11", "CHANNEL_5G": "149", "MOBILITY_DOMAIN": "ABCD", "COUNTRY": "CN"})
        self.assertEqual((profile["ssid_2g"], profile["ssid_5g"]), ("客厅 Wi-Fi", "客厅_5G"))
        self.assertEqual((profile["channel_2g"], profile["channel_5g"]), ("11", "149"))
        self.assertEqual((profile["mobility_domain_2g"], profile["mobility_domain_5g"]), ("abcd", "abcd"))

    def test_empty_5g_ssid_follows_2g(self):
        profile = build_profile(self.base, {"WIFI_SSID": "Home-New", "WIFI_SSID_5G": ""})
        self.assertEqual(profile["ssid_5g"], "Home-New")

    def test_password_input_overrides_secret_then_base(self):
        for key, field in (("WIFI_KEY", "wifi_password"), ("ROOT_PASSWORD", "root_password")):
            with self.subTest(key=key):
                self.assertEqual(build_profile(self.base, {key: "Input-98765", key + "_SECRET": "Secret-98765"})[field], "Input-98765")
                self.assertEqual(build_profile(self.base, {key: "", key + "_SECRET": "Secret-98765"})[field], "Secret-98765")
                self.assertEqual(build_profile(self.base, {key: "", key + "_SECRET": ""})[field], self.base[field])

    def test_invalid_inputs_fail_before_compiling(self):
        for env in ({"WIFI_KEY": "short"}, {"WIFI_SSID": "x\n"}, {"MOBILITY_DOMAIN": "zzzz"}, {"ROOT_PASSWORD": "a\nb"}, {"CHANNEL_2G": "$(id)"}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                build_profile(self.base, env)

    def test_private_file_and_public_source_hide_custom_passwords(self):
        profile = build_profile(self.base, {"WIFI_KEY": secrets.token_hex(16), "ROOT_PASSWORD": secrets.token_hex(16), "CHANNEL_2G": "11"})
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            private = directory / "profile.json"
            write_private_profile(private, profile)
            self.assertEqual(private.stat().st_mode & 0o777, 0o600)
            self.assertEqual(read_json(private), profile)
            archive = directory / "source.zip"
            source_zip(archive, None, profile=profile)
            with zipfile.ZipFile(archive) as stream:
                data = b"\n".join(stream.read(name) for name in stream.namelist())
                public = stream.read(f"AP8220-AP-LEDE-v{version()}/本次出厂参数（不含密码）.json").decode()
            self.assertNotIn(profile["wifi_password"].encode(), data)
            self.assertNotIn(profile["root_password"].encode(), data)
            self.assertIn('"channel_2g": "11"', public)
        self.assertNotIn("wifi_password", public_profile(profile))
        self.assertNotIn("root_password", public_profile(profile))

    def test_built_profile_and_management_hash_are_verified(self):
        profile = build_profile(self.base, {"WIFI_SSID": "Home-Custom", "WIFI_KEY": "My-WiFi-98765", "ROOT_PASSWORD": "My-Root-98765", "CHANNEL_2G": "11"})
        lock = {"firmware_version": f"v{version()}-R26.10.23-b1.1", "lean": {"commit": "a" * 40}, "build_commit": "b" * 40, "built_at": "2026-10-23"}
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            generate_package(tree, lock, profile)
            values = shell_values((tree / "package/custom/ap8220-ap-defaults/files/usr/share/ap8220-ap/defaults.conf").read_text())
            check_built_profile(values, profile)
            with self.assertRaises(ValueError):
                check_built_profile(values, dict(profile, root_password="Wrong-98765"))
            with self.assertRaises(ValueError):
                check_built_profile(values, dict(profile, wifi_password="Wrong-98765"))
            with self.assertRaises(ValueError):
                check_built_profile(values, dict(profile, channel_2g="1"))

    def test_password_log_mask_escapes_workflow_commands(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), contextlib.redirect_stdout(output):
            mask_password("test%\r\nvalue")
        self.assertEqual(output.getvalue(), "::add-mask::test%25%0D%0Avalue\n")

    def test_workflow_passes_inputs_via_environment_and_private_profile(self):
        import yaml
        workflow = yaml.load((ROOT / ".github/workflows/编译发布.yml").read_text(), Loader=yaml.BaseLoader)
        inputs = workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(len(inputs), 10)
        steps = workflow["jobs"]["build"]["steps"]
        parameter_step = next(step for step in steps if "configure_profile.py" in step.get("run", ""))
        self.assertEqual(parameter_step["env"]["ROOT_PASSWORD"], "${{ inputs.root_password }}")
        self.assertEqual(parameter_step["env"]["WIFI_KEY_SECRET"], "${{ secrets.WIFI_KEY }}")
        for step in steps:
            self.assertNotIn("${{ inputs.", step.get("run", ""))
            if any(name in step.get("run", "") for name in ("scripts/prepare.py", "scripts/collect.py")):
                self.assertIn("--profile work/ap-profile.json", step["run"])
