#!/usr/bin/env python3
"""根据版本锁准备 Lean、软件源和 AP 专用配置。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from apbuild import (
    ROOT, check_config, fetch_text, main_guard, read_json,
    replace_router_defaults, run, validate_profile, version,
)
from layouts import LAYOUTS, adapt_tree
from footstrap import install_theme


def checkout(url, commit, destination):
    if destination.exists():
        raise ValueError(f"目标目录已经存在，请使用新的构建目录：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "-q", str(destination)])
    run(["git", "remote", "add", "origin", url], cwd=destination)
    run(["git", "fetch", "--depth=1", "origin", commit], cwd=destination)
    run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=destination)
    if run(["git", "rev-parse", "HEAD"], cwd=destination, capture=True) != commit:
        raise ValueError("检出的 Lean 提交与版本锁不一致")


def generate_package(tree, lock, profile, layout="large128"):
    package = tree / "package/custom/ap8220-ap-defaults"
    shutil.copytree(ROOT / "package/ap8220-ap-defaults", package)
    makefile = package / "Makefile"
    content = makefile.read_text(encoding="utf-8")
    if content.count("PKG_VERSION:=@SOURCE_VERSION@") != 1:
        raise ValueError("默认配置包的版本模板无效")
    makefile.write_text(content.replace("@SOURCE_VERSION@", version()), encoding="utf-8")
    shared = package / "files/usr/share/ap8220-ap"
    shared.mkdir(parents=True, exist_ok=True)
    # 不把设备 root 密码以明文安装到固件；使用 SHA-512 crypt。
    hashed = subprocess.run(
        ["openssl", "passwd", "-6", "-stdin"], input=profile["root_password"] + "\n",
        text=True, capture_output=True, check=True,
    ).stdout.strip()
    values = {key.upper(): value for key, value in profile.items() if key != "root_password"}
    values["ROOT_PASSWORD_HASH"] = hashed
    values["SOURCE_VERSION"] = version()
    values["FIRMWARE_VERSION"] = lock["firmware_version"]
    lines = ["# 由构建程序生成：AP8220 AP 专用默认参数。"]
    for key, value in values.items():
        if isinstance(value, bool):
            value = "1" if value else "0"
        lines.append(f"{key}={shlex.quote(str(value))}")
    defaults = shared / "defaults.conf"
    defaults.write_text("\n".join(lines) + "\n", encoding="utf-8")
    defaults.chmod(0o600)
    etc = package / "files/etc"
    release = {
        "SOURCE_VERSION": version(),
        "FIRMWARE_VERSION": lock["firmware_version"],
        "LEAN_COMMIT": lock["lean"]["commit"],
        "BUILD_COMMIT": lock["build_commit"],
        "BUILD_DATE": lock["built_at"],
        "FLASH_LAYOUT": layout,
    }
    (etc / "ap8220-ap-release").write_text(
        "# AP8220 AP 专用固件版本信息\n" +
        "\n".join(f"{key}={shlex.quote(value)}" for key, value in release.items()) + "\n",
        encoding="utf-8",
    )
    public_lock = dict(lock)
    (shared / "sources.lock.json").write_text(json.dumps(public_lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for path in package.rglob("*"):
        if path.is_file() and ("/init.d/" in str(path) or "/uci-defaults/" in str(path) or "/usr/sbin/" in str(path)):
            path.chmod(0o755)


def configure(tree, lock, layout="large128"):
    target = tree / "include/target.mk"
    target.write_text(replace_router_defaults(target.read_text()), encoding="utf-8")
    # 保留上游的驱动和 NSS 默认包，仅移除 AP 无需的磁盘工具。
    target_makefile = tree / "target/linux/qualcommax/Makefile"
    text = target_makefile.read_text()
    for name in ("e2fsprogs", "f2fsck", "mkf2fs", "losetup", "automount"):
        text = re.sub(rf"(?<![\w-]){name}(?![\w-])", "", text)
    target_makefile.write_text(text, encoding="utf-8")
    adapt_tree(tree, layout)
    config = (ROOT / "config/ap8220-ap.config").read_text(encoding="utf-8")
    config += (
        '\nCONFIG_VERSIONOPT=y\nCONFIG_VERSION_FILENAMES=y\n'
        'CONFIG_VERSION_DIST="AP8220-AP"\n'
        f'CONFIG_VERSION_NUMBER="{version()}"\n'
        f'CONFIG_VERSION_CODE="{lock["build_code"]}"\n'
    )
    if layout == "stock":
        config += '\nCONFIG_TARGET_ROOTFS_INITRAMFS=y\nCONFIG_TARGET_INITRAMFS_COMPRESSION_XZ=y\n'
    (tree / ".config").write_text(config, encoding="utf-8")
    run(["make", "defconfig"], cwd=tree)
    check_config((tree / ".config").read_text(), read_json(ROOT / "config/package-policy.json"))
    print("AP8220 目标、NSS、Turboacc、漫游和软件包配置检查通过。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--existing-tree", action="store_true", help="仅供离线检查已准备的源码目录")
    parser.add_argument("--profile", type=Path, default=ROOT / "config/ap-defaults.json", help="本次编译的出厂参数文件")
    parser.add_argument("--layout", choices=LAYOUTS, default="large128")
    args = parser.parse_args()
    lock = read_json(args.lock)
    if lock["source_version"] != version():
        raise ValueError("版本锁与源码 VERSION 不一致")
    profile = read_json(args.profile)
    validate_profile(profile)
    tree = args.tree.resolve()
    if not args.existing_tree:
        checkout(lock["lean"]["url"], lock["lean"]["commit"], tree)
    if not (tree / "include/target.mk").is_file():
        raise ValueError("不是有效的 Lean 源码目录")
    feeds = [
        f'{item["method"]} {item["name"]} {item["url"]}^{item["commit"]}'
        for item in lock["feeds"]
    ]
    (tree / "feeds.conf").write_text("\n".join(feeds) + "\n", encoding="utf-8")
    # feeds 对 ^SHA 默认进行全历史克隆；这里浅检出精确提交，再只生成索引。
    for item in lock["feeds"]:
        destination = tree / "feeds" / item["name"]
        if not destination.exists():
            checkout(item["url"], item["commit"], destination)
        actual = run(["git", "rev-parse", "HEAD"], cwd=destination, capture=True)
        if actual != item["commit"]:
            raise ValueError(f'软件源 {item["name"]} 的版本与锁文件不一致')
    recipe = fetch_text(lock["usteer_recipe"]["url"])
    if hashlib.sha256(recipe.encode()).hexdigest() != lock["usteer_recipe"]["sha256"]:
        raise ValueError("usteer 配方的校验值不一致")
    usteer = tree / "feeds/packages/net/usteer/Makefile"
    if not usteer.is_file():
        raise ValueError("Lean 软件源中的 usteer 目录发生变化，需要人工适配")
    usteer.write_text(recipe, encoding="utf-8")
    install_theme(tree, lock, checkout)
    run(["./scripts/feeds", "update", "-i", *[item["name"] for item in lock["feeds"]]], cwd=tree)
    run(["./scripts/feeds", "install", "-a"], cwd=tree)
    generate_package(tree, lock, profile, args.layout)
    configure(tree, lock, args.layout)


if __name__ == "__main__":
    main_guard(main)
