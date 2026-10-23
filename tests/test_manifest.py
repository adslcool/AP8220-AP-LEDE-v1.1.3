"""回归实际镜像清单带 ABI 后缀而配置包名不带后缀的交付故障。"""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from package_manifest import check_manifest, installed_name, manifest_packages


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.tree = Path(self.temporary.name)
        self.info = self.tree / "staging_dir/target-aarch64_cortex-a53_musl/pkginfo"
        self.info.mkdir(parents=True)
        self.policy = {"required": ["libustream-openssl", "usteer"], "forbidden": ["libustream-mbedtls"]}

    def tearDown(self):
        self.temporary.cleanup()

    def abi(self, name, value="20201210"):
        (self.info / (name + ".version")).write_text(value + "\n")

    def test_real_lean_abi_suffix_is_accepted(self):
        self.abi("libustream-openssl")
        packages = manifest_packages("libustream-openssl20201210 - 2026.03.01~99f1c0db-r1\nusteer - 2026.05.19~7532e125-r1\n")
        self.assertEqual(check_manifest(packages, self.policy, self.tree)["libustream-openssl"], "libustream-openssl20201210")

    def test_package_without_abi_uses_exact_name(self):
        check_manifest({"libustream-openssl": "1", "usteer": "2"}, self.policy, self.tree)

    def test_really_missing_openssl_is_rejected(self):
        self.abi("libustream-openssl")
        with self.assertRaises(ValueError):
            check_manifest({"usteer": "2"}, self.policy, self.tree)

    def test_wrong_abi_or_arbitrary_prefix_is_rejected(self):
        self.abi("libustream-openssl")
        for name in ("libustream-openssl20201211", "libustream-openssl-extra", "libustream-openssl"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                check_manifest({name: "1", "usteer": "2"}, self.policy, self.tree)

    def test_forbidden_backend_with_abi_is_rejected(self):
        self.abi("libustream-openssl")
        self.abi("libustream-mbedtls")
        with self.assertRaises(ValueError):
            check_manifest({"libustream-openssl20201210": "1", "libustream-mbedtls20201210": "1", "usteer": "2"}, self.policy, self.tree)

    def test_numeric_package_name_uses_separator(self):
        self.abi("libexample2", "3")
        self.assertEqual(installed_name(self.tree, "libexample2"), "libexample2-3")

    def test_kernel_modules_keep_their_name(self):
        self.abi("kmod-example", "123")
        self.assertEqual(installed_name(self.tree, "kmod-example"), "kmod-example")

    def test_ambiguous_or_invalid_abi_is_rejected(self):
        self.abi("libustream-openssl", "bad value")
        with self.assertRaises(ValueError):
            installed_name(self.tree, "libustream-openssl")
        self.abi("libustream-openssl")
        other = self.tree / "staging_dir/target-other/pkginfo"
        other.mkdir(parents=True)
        (other / "libustream-openssl.version").write_text("20201210\n")
        with self.assertRaises(ValueError):
            installed_name(self.tree, "libustream-openssl")
