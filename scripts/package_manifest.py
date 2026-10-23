#!/usr/bin/env python3
"""根据本次 Lean 的 ABI 元数据核验镜像中的实际软件包名称。"""
from pathlib import Path
import re


def manifest_packages(text):
    result = {}
    for line in text.splitlines():
        name, separator, package_version = line.partition(" - ")
        if not separator or name in result:
            raise ValueError("软件包清单格式无效或有重复包")
        result[name] = package_version
    return result


def installed_name(tree: Path, name: str) -> str:
    # 与 Lean include/feeds.mk 的 FormatABISuffix 规则一致。
    # 不按前缀或任意日期猜测名称，只使用本次构建实际生成的 ABI 版本。
    if name.startswith("kmod-"):
        return name
    metadata = list((tree / "staging_dir").glob(f"target-*/pkginfo/{name}.version"))
    if len(metadata) > 1:
        raise ValueError(f"软件包 ABI 元数据不唯一：{name}")
    if not metadata:
        return name
    abi = metadata[0].read_text(encoding="utf-8").strip()
    if not abi or not re.fullmatch(r"[A-Za-z0-9.+~_-]+", abi):
        raise ValueError(f"软件包 ABI 元数据无效：{name}")
    separator = "-" if name[-1].isdigit() else ""
    return name + separator + abi


def check_manifest(packages, policy, tree):
    resolved = {name: installed_name(tree, name) for name in policy["required"] + policy["forbidden"]}
    missing = sorted(name for name in policy["required"] if resolved[name] not in packages)
    forbidden = sorted(
        name for name in policy["forbidden"] if name in packages or resolved[name] in packages
    )
    if missing or forbidden:
        hints = {name: resolved[name] for name in missing if name != resolved[name]}
        raise ValueError(f"实际软件包清单未通过检查；缺少：{missing}；禁止：{forbidden}；ABI 实际名称：{hints}")
    return resolved
