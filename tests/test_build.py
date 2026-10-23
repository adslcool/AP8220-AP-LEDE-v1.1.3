"""版本锁、包策略与上游变更保护测试。"""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from apbuild import ROOT, check_config, config_values, parse_feeds, read_json, replace_router_defaults, validate_profile
from collect import manifest_packages


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.config = (ROOT / "config/ap8220-ap.config").read_text()
        self.policy = read_json(ROOT / "config/package-policy.json")

    def test_ap_package_selection(self):
        check_config(self.config, self.policy)

    def test_missing_turboacc_is_rejected(self):
        with self.assertRaises(ValueError):
            check_config(self.config.replace("CONFIG_PACKAGE_luci-app-turboacc=y", ""), self.policy)

    def test_proxy_module_is_rejected(self):
        text = self.config.replace("# CONFIG_PACKAGE_tailscale is not set", "CONFIG_PACKAGE_tailscale=m")
        with self.assertRaises(ValueError):
            check_config(text, self.policy)

    def test_duplicate_config_is_rejected(self):
        with self.assertRaises(ValueError):
            config_values("CONFIG_X=y\n# CONFIG_X is not set\n")

    def test_upstream_router_defaults_only(self):
        before = "before\nDEFAULT_PACKAGES.router:=\\\n\tluci ppp \\\n\tproxy foo\n\nafter\n"
        after = replace_router_defaults(before)
        self.assertIn("firewall4 nftables-json odhcp6c ip-full ca-certificates", after)
        self.assertTrue(after.endswith("\nafter\n"))
        self.assertNotIn("proxy", after)

    def test_changed_upstream_layout_stops_build(self):
        with self.assertRaises(ValueError):
            replace_router_defaults("DEFAULT_PACKAGES.router = changed\n")

    def test_feed_branches_and_exclusions(self):
        entries = parse_feeds(
            "src-git packages https://github.com/coolsnowwolf/packages.git\n"
            "src-git luci https://github.com/coolsnowwolf/luci.git;openwrt-25.12\n"
            "src-git helloworld https://github.com/fw876/helloworld.git\n"
        )
        self.assertEqual([item["name"] for item in entries], ["packages", "luci"])
        self.assertEqual(entries[1]["ref"], "openwrt-25.12")

    def test_bad_feed_format_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_feeds("src-link custom /tmp/unlocked\n")

    def test_manifest_duplicates_are_rejected(self):
        with self.assertRaises(ValueError):
            manifest_packages("luci-base - 1\nluci-base - 2\n")

    def test_default_wireless_profile(self):
        validate_profile(read_json(ROOT / "config/ap-defaults.json"))

    def test_invalid_or_oversized_ssid_is_rejected(self):
        profile = read_json(ROOT / "config/ap-defaults.json")
        for ssid in ("中" * 11, "bad\nssid", "bad'ssid"):
            bad = copy.deepcopy(profile)
            bad["ssid_2g"] = ssid
            with self.assertRaises(ValueError):
                validate_profile(bad)

    def test_unified_ssid_requires_shared_mobility_domain(self):
        profile = read_json(ROOT / "config/ap-defaults.json")
        profile["ssid_5g"] = profile["ssid_2g"]
        profile["mobility_domain_5g"] = "ffff"
        with self.assertRaises(ValueError):
            validate_profile(profile)
        profile["mobility_domain_5g"] = profile["mobility_domain_2g"]
        validate_profile(profile)
