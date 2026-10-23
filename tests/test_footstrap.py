"""检查锁定主题的中文覆盖和 gettext 上下文、占位符。"""
from pathlib import Path
import sys
import unittest
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from apbuild import ROOT,read_json
from footstrap import po_messages,validate_translation,install_theme


class FootstrapTests(unittest.TestCase):
    def test_full_chinese_and_frozen_official_source(self):
        po=(ROOT/'config/footstrap.zh-cn.po').read_text()
        self.assertEqual(validate_translation(po),117)
        source=read_json(ROOT/'config/footstrap-source.json')
        self.assertEqual(source['url'],'https://github.com/openwrt/luci.git')
        self.assertRegex(source['commit'],r'^[0-9a-f]{40}$')
        self.assertRegex(source['template_sha256'],r'^[0-9a-f]{64}$')
        self.assertIn(('footstrap','Colours'),po_messages(po))

    def test_missing_word_and_bad_placeholder_are_rejected(self):
        original='msgctxt "footstrap"\nmsgid "Count %d"\nmsgstr ""\n'
        with self.assertRaises(ValueError):
            validate_translation(original)
        with self.assertRaises(ValueError):
            validate_translation(original.replace('msgstr ""','msgstr "数量 %s"'))
        with self.assertRaises(ValueError):
            validate_translation(original.replace('msgstr ""','msgstr "数量 %d"'),original+'\nmsgid "Missing"\nmsgstr ""\n')

    def test_duplicate_translation_context_is_rejected(self):
        entry='msgctxt "footstrap"\nmsgid "Theme"\nmsgstr "主题"\n\n'
        with self.assertRaises(ValueError):
            validate_translation(entry+entry)

    def test_partial_theme_checkout_is_outside_build_tree_and_cleaned(self):
        source=read_json(ROOT/'config/footstrap-source.json')
        created=[]
        with tempfile.TemporaryDirectory() as temporary:
            tree=Path(temporary)/'openwrt';tree.mkdir()
            def failing_checkout(url,commit,destination):
                self.assertFalse(destination.is_relative_to(tree))
                destination.mkdir();(destination/'partial').write_text('partial download')
                created.append(destination)
                raise ValueError('模拟克隆失败')
            with self.assertRaisesRegex(ValueError,'模拟克隆失败'):
                install_theme(tree,{'footstrap':source},failing_checkout)
        self.assertFalse(created[0].exists())
