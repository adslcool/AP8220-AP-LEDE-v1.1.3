"""接入固定提交的 OpenWrt 官方 Footstrap，并检查本项目简体中文翻译。"""
import ast
from collections import Counter
import hashlib
from pathlib import Path
import re
import shutil
import tempfile

from apbuild import ROOT, read_json


def po_messages(text):
    result, entry, current = {}, {}, None
    for line in (text + "\n\n").splitlines():
        if not line.strip():
            if entry.get("msgid"):
                key = (entry.get("msgctxt", ""), entry["msgid"])
                if key in result:
                    raise ValueError("翻译词条重复")
                result[key] = entry.get("msgstr", "")
            entry, current = {}, None
        elif line.startswith("#"):
            continue
        elif line.startswith('"'):
            if current is None:
                raise ValueError("翻译续行没有字段")
            entry[current] += ast.literal_eval(line)
        else:
            current, separator, value = line.partition(" ")
            if not separator or current not in {"msgctxt", "msgid", "msgstr"}:
                raise ValueError("尚未支持的 PO 字段")
            entry[current] = ast.literal_eval(value)
    return result


def validate_translation(translation, template=None):
    messages = po_messages(translation)
    if not messages or any(not value.strip() for value in messages.values()):
        raise ValueError("Footstrap 中文翻译有空词条")
    if template is not None and set(messages) != set(po_messages(template)):
        raise ValueError("Footstrap 中文词条与固定版本模板不一致")
    for (_, original), translated in messages.items():
        placeholders = r"%[0-9$.*+-]*[sdifu]"
        if Counter(re.findall(placeholders, original)) != Counter(re.findall(placeholders, translated)):
            raise ValueError("Footstrap 翻译占位符不一致：" + original)
    return len(messages)


def install_theme(tree: Path, lock, checkout):
    source = read_json(ROOT / "config/footstrap-source.json")
    if lock.get("footstrap") != source:
        raise ValueError("Footstrap 源码锁与本项目声明不一致")
    # 放到源码树之外，避免上游扫描器为已删除的临时配方重建同名目录。
    with tempfile.TemporaryDirectory(prefix="ap8220-footstrap-") as work:
        temporary = Path(work) / "source"
        checkout(source["url"], source["commit"], temporary)
        directory = temporary / "themes/luci-theme-footstrap"
        template = (directory / "po/templates/footstrap.pot").read_bytes()
        if hashlib.sha256(template).hexdigest() != source["template_sha256"]:
            raise ValueError("Footstrap 固定模板哈希不一致")
        translation = ROOT / "config/footstrap.zh-cn.po"
        validate_translation(translation.read_text(), template.decode())
        destination = tree / "feeds/luci/themes/luci-theme-footstrap"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(directory, destination)
        chinese = destination / "po/zh_Hans"
        chinese.mkdir(exist_ok=True)
        shutil.copy2(translation, chinese / "footstrap.po")
