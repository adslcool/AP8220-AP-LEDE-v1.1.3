#!/usr/bin/env python3
"""核验随固件交付的引导文件；缺少原厂 U-Boot 时阻止完整发布。"""
import argparse
import hashlib
from pathlib import Path
import struct

from apbuild import ROOT, main_guard, read_json

THIRD_PARTY_SHA = "2e1e61ed0fd7a5d64695e5e40ab7c56b2d00ba447454cc61bb5315f458366c27"


def mibib_rows(data):
    if len(data) != 65536 or struct.unpack_from("<III", data, 0x100) != (0x55ee73aa, 0xe35ebddb, 4):
        raise ValueError("MIBIB 格式或大小不正确")
    count = struct.unpack_from("<I", data, 0x10c)[0]
    if count not in (15, 17):
        raise ValueError("MIBIB 分区数量不正确")
    rows = []
    for index in range(count):
        name, offset, size, flags = struct.unpack_from("<16sIII", data, 0x110 + 28 * index)
        rows.append((name.rstrip(b"\0").decode("ascii"), offset, size, flags))
    return rows


def check_assets(require_complete=False, root=None):
    root = root or ROOT / "boot-assets"
    record = read_json(root / "来源与检查记录.json")
    for entry in record["文件"]:
        path = root / entry["文件"]
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("启动文件路径越界")
        if entry["文件"] == "stock/ap8220-stock-uboot.bin" and not path.exists():
            # 原厂备份缺失的场景统一由后面的完整性检查报告。
            continue
        data = path.read_bytes()
        if len(data) != entry["字节数"] or hashlib.sha256(data).hexdigest() != entry["SHA256"]:
            raise ValueError("启动文件大小或哈希不匹配：" + entry["文件"])
    stock = mibib_rows((root / "stock/ap8220-stock-mibib.bin").read_bytes())
    large = mibib_rows((root / "large128/ap8220-large128-mibib.bin").read_bytes())
    if stock[:14] != large[:14] or len(stock) != 17 or len(large) != 15:
        raise ValueError("两种 MIBIB 的 SPI 区域或 NAND 分区数量不匹配")
    if stock[14:] != [("rootfs1", 0, 0x180, 0x100ffff), ("rootfs2", 0x180, 0x180, 0x100ffff), ("usrdata", 0x300, 0xffffffff, 0x100ffff)]:
        raise ValueError("原厂 MIBIB 不是 48+48+剩余空间布局")
    if large[14:] != [("rootfs", 0, 0x400, 0x100ffff)]:
        raise ValueError("大分区 MIBIB 不是单 rootfs 128MiB")
    info = root / "stock/uboot-info.json"
    boot = root / "stock/ap8220-stock-uboot.bin"
    if not info.exists() or not boot.exists():
        if require_complete:
            raise ValueError("原厂 U-Boot 缺失：先从仍保留原厂引导的 AP8220 备份 0:APPSBL，再运行 scripts/add_stock_uboot.py；发布已提前停止。关闭 publish 可只验证两种固件编译。")
        return False
    provenance = read_json(info)
    data = boot.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != 655360 or digest == THIRD_PARTY_SHA or digest != provenance.get("sha256") or not provenance.get("origin"):
        raise ValueError("原厂 U-Boot 大小、来源或哈希检查失败；不得把本包第三方 U-Boot 改名冒充原厂文件")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    complete = check_assets(args.require_complete)
    print("启动文件检查通过；" + ("两种资料完整。" if complete else "原厂 U-Boot 仍待补齐，暂不可完整发布。"))


if __name__ == "__main__":
    main_guard(main)
