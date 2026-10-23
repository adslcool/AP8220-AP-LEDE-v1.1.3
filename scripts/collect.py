#!/usr/bin/env python3
"""核验实际镜像并生成带版本号的固件、源码包和中文发布说明。"""
import argparse
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

from apbuild import ROOT, check_config, main_guard, read_json, sha256_file, validate_profile, version, write_json
from configure_profile import public_profile
from images import same_squashfs, ubi_volumes, validate_ap8220_fit, validate_stock_boot
from package_manifest import check_manifest, manifest_packages
from layouts import LAYOUTS


def shell_values(text):
    result = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key in result:
            raise ValueError("固件参数中有重复项")
        tokens = shlex.split(value)
        if len(tokens) != 1:
            raise ValueError("固件参数格式无效")
        result[key] = tokens[0]
    return result


def check_built_profile(values, profile):
    for key, value in profile.items():
        if key == "root_password":
            continue
        expected = ("1" if value else "0") if isinstance(value, bool) else str(value)
        if values.get(key.upper()) != expected:
            raise ValueError(f"实际镜像的出厂参数与本次编译输入不一致：{key}")
    hashed = values.get("ROOT_PASSWORD_HASH", "")
    match = re.fullmatch(r"\$6\$([A-Za-z0-9./]{1,16})\$[A-Za-z0-9./]{86}", hashed)
    if not match:
        raise ValueError("实际镜像的管理密码哈希无效")
    expected = subprocess.run(
        ["openssl", "passwd", "-6", "-salt", match.group(1), "-stdin"],
        input=profile["root_password"] + "\n", text=True, capture_output=True, check=True,
    ).stdout.strip()
    if expected != hashed:
        raise ValueError("实际镜像的管理密码与本次编译输入不一致")


def unique_file(directory, pattern):
    paths = sorted(directory.glob(pattern))
    if len(paths) != 1:
        raise ValueError(f"交付文件必须唯一：{pattern}，实际数量 {len(paths)}")
    return paths[0]


def source_zip(destination, lock, config_text=None, profile=None):
    selected = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if path.is_file() and not any(
            part in {".git", "__pycache__", ".cache", "work", "release", "openwrt"} for part in relative.parts
        ) and path.suffix not in {".pyc", ".log", ".zip"}:
            selected.append(path)
    if not selected or len(selected) > 100:
        raise ValueError("源码包文件数量异常或超过 100 个")
    prefix = f"AP8220-AP-LEDE-v{version()}"
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(selected):
            archive.write(path, f"{prefix}/{path.relative_to(ROOT).as_posix()}")
        if lock:
            archive.writestr(f"{prefix}/构建版本锁.json", json.dumps(lock, ensure_ascii=False, indent=2) + "\n")
        if config_text:
            archive.writestr(f"{prefix}/本次完整编译配置.config", config_text)
        if profile is not None:
            archive.writestr(f"{prefix}/本次出厂参数（不含密码）.json", json.dumps(public_profile(profile), ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=ROOT / "config/ap-defaults.json")
    parser.add_argument("--layout", choices=LAYOUTS, default="large128")
    args = parser.parse_args()
    tree = args.tree.resolve()
    profile = read_json(args.profile)
    validate_profile(profile)
    lock = read_json(args.lock)
    if lock["source_version"] != version():
        raise ValueError("源码版本与构建锁不一致")
    if not re.fullmatch(r"v\d+\.\d+\.\d+-R\d{2}\.\d{2}\.\d{2}-b[0-9]+\.[0-9]+", lock["firmware_version"]):
        raise ValueError("正式交付必须由 GitHub Actions 生成构建编号")
    directory = tree / "bin/targets/qualcommax/ipq807x"
    factory = unique_file(directory, "*aliyun_ap8220*squashfs-factory.ubi")
    upgrade = unique_file(directory, "*aliyun_ap8220*squashfs-sysupgrade.bin")
    manifest = unique_file(directory, "*aliyun_ap8220.manifest")
    config_text = (tree / ".config").read_text()
    policy = read_json(ROOT / "config/package-policy.json")
    check_config(config_text, policy)
    packages = manifest_packages(manifest.read_text())
    check_manifest(packages, policy, tree)
    if not packages["ap8220-ap-defaults"].startswith(version() + "-"):
        raise ValueError("默认配置包版本与源码版本不一致")
    with tarfile.open(upgrade, "r:") as archive:
        members = {member.name: member for member in archive.getmembers() if member.isfile()}
        prefix = "sysupgrade-aliyun_ap8220/"
        for name in ("CONTROL", "kernel", "root"):
            if prefix + name not in members:
                raise ValueError(f"Sysupgrade 缺少 {name}")
        control = archive.extractfile(members[prefix + "CONTROL"]).read().decode()
        if not re.search(r"(?m)^BOARD=aliyun_ap8220$", control):
            raise ValueError("Sysupgrade 的设备名称不匹配")
        kernel = archive.extractfile(members[prefix + "kernel"]).read()
        root = archive.extractfile(members[prefix + "root"]).read()
    if root[:4] != b"hsqs":
        raise ValueError("Sysupgrade 根文件系统不是 SquashFS")
    validate_ap8220_fit(kernel, args.layout, require_layout_marker=True)
    boot_memory = {"普通内核": validate_stock_boot(kernel)} if args.layout == "stock" else None
    if factory.stat().st_size > LAYOUTS[args.layout]["limit"]:
        raise ValueError("Factory 镜像超过该布局的容量预算，无法预留 UBI、坏块与可写空间")
    initramfs = None
    if args.layout == "stock":
        initramfs = unique_file(directory, "*aliyun_ap8220-initramfs-uImage.itb")
        validate_ap8220_fit(initramfs.read_bytes(), args.layout, require_layout_marker=True)
        boot_memory["首刷内存镜像"] = validate_stock_boot(initramfs.read_bytes())
    volumes = ubi_volumes(factory.read_bytes())
    if not volumes.get("kernel", b"").startswith(kernel) or not same_squashfs(volumes.get("rootfs", b""), root):
        raise ValueError("Factory 和 Sysupgrade 的内核或根文件系统不一致")
    with tempfile.TemporaryDirectory(prefix="ap8220-release-") as temporary:
        temporary = Path(temporary)
        root_file = temporary / "root.squashfs"
        root_file.write_bytes(root)
        actual = subprocess.run(
            ["unsquashfs", "-cat", str(root_file), "etc/ap8220-ap-release"],
            text=True, capture_output=True, check=True,
        ).stdout
        actual_values = shell_values(actual)
        if actual_values.get("SOURCE_VERSION") != version() or actual_values.get("FIRMWARE_VERSION") != lock["firmware_version"]:
            raise ValueError("固件内部版本信息与交付文件名不一致")
        if actual_values.get("FLASH_LAYOUT") != args.layout:
            raise ValueError("固件内部布局标记与交付文件不一致")
        defaults = subprocess.run(
            ["unsquashfs", "-cat", str(root_file), "usr/share/ap8220-ap/defaults.conf"],
            text=True, capture_output=True, check=True,
        ).stdout
        check_built_profile(shell_values(defaults), profile)
        fwtool = tree / "staging_dir/host/bin/fwtool"
        metadata_file = temporary / "metadata.json"
        subprocess.run([str(fwtool), "-i", str(metadata_file), str(upgrade)], check=True)
        metadata = read_json(metadata_file)
        if "aliyun,ap8220" not in metadata.get("supported_devices", []):
            raise ValueError("Sysupgrade 元数据未声明 AP8220")
        if metadata.get("ap8220_layout") != args.layout:
            raise ValueError("Sysupgrade 缺少匹配的分区布局元数据")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("交付目录非空，拒绝混入旧版文件")
    output.mkdir(parents=True, exist_ok=True)
    label = "AP8220-AP-" + lock["firmware_version"] + "-" + args.layout
    shutil.copy2(factory, output / f"{label}-factory.ubi")
    shutil.copy2(upgrade, output / f"{label}-sysupgrade.bin")
    if initramfs:
        shutil.copy2(initramfs, output / f"{label}-initramfs-uImage.itb")
    shutil.copy2(manifest, output / f"{label}-软件包清单.manifest")
    (output / f"{label}-编译配置.config").write_text(config_text, encoding="utf-8")
    shutil.copy2(args.lock, output / f"{label}-源码版本锁.json")
    feeds_info = directory / "feeds.buildinfo"
    if feeds_info.exists():
        shutil.copy2(feeds_info, output / f"{label}-软件源版本.buildinfo")
    source_zip(output / f"{label}-源码.zip", lock, config_text, profile)
    write_json(output / f"{label}-出厂参数（不含密码）.json", public_profile(profile))
    details = {
        "固件名称": "AP8220 AP专用固件",
        "源码版本": f"v{version()}",
        "固件版本": lock["firmware_version"],
        "构建时间": lock["built_at"],
        "设备": "阿里云 AP8220",
        "分区要求": LAYOUTS[args.layout]["title"] + "，启动端分区表必须匹配",
        "布局标记": args.layout,
        "原厂启动内存检查": boot_memory,
        "内核版本": packages.get("kernel", ""),
        "加速模式": "NSS ECM，保留 Turboacc 中文页面",
        "无线漫游": "802.11k/v/r 与 usteer 温和策略，有线回程",
        "Lean 源码提交": lock["lean"]["commit"],
        "项目源码提交": lock["build_commit"],
        "构建日志": lock["workflow_run"],
        "本次出厂参数（不含密码）": public_profile(profile),
        "检查结果": "镜像格式、实际设备树、原厂 ART 定义、双镜像内容、软件包与内部版本检查通过",
        "实机状态": "本次自动构建未执行硬件刷入和漫游测试",
    }
    write_json(output / f"{label}-构建信息.json", details)
    notes = f"""# AP8220 AP专用固件 {lock['firmware_version']}

源码版本：v{version()}。构建时间：{lock['built_at']}。

适用于原版阿里云 AP8220，布局：{args.layout}（{LAYOUTS[args.layout]['title']}）。启动端须先具备匹配的 U-Boot 与 MIBIB；固件正常升级不修改它们。

## 默认设置

- 两个有线口桥接；AP 管理地址、客户端地址均由上级路由器 DHCP 分配。
- 保留 IPv6 桥接通行；AP 不提供 DHCP、DHCPv6 或 RA 服务。
- 预装简体中文 LuCI、Footstrap 及中文包、Argon、Turboacc、NSS ECM、完整 wpad 与 usteer。
- MAC 从本机 product_info 读取；从本项目旧版升级会迁移自动身份，管理 DHCP 地址可能变化。
- 本次出厂参数见交付的“出厂参数（不含密码）.json”；编译表单输入优先于源码中的基础参数。
- 管理密码与无线密码不写入发布说明或源码包；复现时重新提供。固件包含正常使用所需的无线密码与 root 哈希，下载者能够读取。
- 首次安装与恢复出厂时应用默认设置；本项目后续保留配置升级不会覆盖用户网络设置。

## 文件用途

- factory.ubi：完成匹配分区准备后，供支持 NAND Factory UBI 的 Web U-Boot 首次刷入。
- sysupgrade.bin：本项目同分区布局内的系统升级。首次从其他固件迁入请勿保留配置。
- 源码.zip：本次项目构建源码、完整编译配置与上游版本锁；上游 Lean 和软件源按锁文件下载。
- 其他文件：简体中文构建信息、软件包清单、配置、版本锁与 SHA256 校验。

已通过自动交付检查。硬件启动、NSS 实际加速和不同终端的漫游效果仍需首轮实机验收。

stock 另通过普通内核与 initramfs 的实际解压内存范围检查，但尚需原厂 U-Boot 实机启动验收。日志应显示 FIT 暂存 0x42000000、内核 Load Address 0x44000000。

Lean 提交：{lock['lean']['commit']}

构建日志：{lock['workflow_run']}
"""
    (output / "发布说明.md").write_text(notes, encoding="utf-8")
    checksums = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(output.iterdir()) if path.is_file() and path.name != "sha256sums"
    ]
    (output / "sha256sums").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    count = len(list(output.iterdir()))
    if count > 20:
        raise ValueError("交付文件数量超出预期")
    github_output = __import__("os").environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as stream:
            stream.write(f"tag={label}\ntitle=AP8220 AP专用固件 {lock['firmware_version']}\n")
    print(f"交付检查通过：{label}，共 {count} 个文件。")


if __name__ == "__main__":
    main_guard(main)
