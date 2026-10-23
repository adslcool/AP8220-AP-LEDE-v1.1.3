#!/usr/bin/env python3
"""导入用户确认来自原厂设备的 APPSBL 备份，只改项目文件，不刷设备。"""
import argparse
import hashlib
from pathlib import Path

from apbuild import ROOT, main_guard, write_json
from boot_assets import THIRD_PARTY_SHA, check_assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--origin", required=True, help="记录原版 AP8220、备份时间及确认仍是原厂 U-Boot 的依据；不要填写密码")
    args = parser.parse_args()
    data = args.file.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != 655360 or digest == THIRD_PARTY_SHA or not args.origin.strip():
        raise ValueError("必须提供原版 AP8220 的原厂 APPSBL 备份，655360 字节；拒绝本包第三方 U-Boot")
    target = ROOT / "boot-assets/stock"
    if (target / "ap8220-stock-uboot.bin").exists() or (target / "uboot-info.json").exists():
        raise ValueError("已有原厂 U-Boot，拒绝覆盖；请先核对当前来源记录")
    (target / "ap8220-stock-uboot.bin").write_bytes(data)
    write_json(target / "uboot-info.json", {"sha256": digest, "size": len(data), "origin": args.origin, "authenticity": "来源由提供者填写；程序核验大小与哈希，不等于官方真实性认证"})
    check_assets(True)
    print("已导入原厂 U-Boot 备份；请把文件和来源记录一并提交仓库。没有向设备写入任何内容。")


if __name__ == "__main__":
    main_guard(main)
