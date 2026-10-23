#!/usr/bin/env python3
"""一次运行分别构建两种布局，检查后释放源码树，保留共同下载与编译缓存。"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from apbuild import ROOT, main_guard, read_json, validate_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    validate_profile(read_json(args.profile))
    environment = dict(os.environ)
    environment.pop("GITHUB_OUTPUT", None)
    downloads = ROOT / "work/downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    tree = ROOT / "openwrt"
    for layout in ("large128", "stock"):
        print(f"::group::准备并编译 {layout}", flush=True)
        subprocess.run([sys.executable, str(ROOT / "scripts/prepare.py"), "--lock", str(args.lock.resolve()), "--profile", str(args.profile.resolve()), "--tree", str(tree), "--layout", layout], env=environment, check=True)
        if (tree / "dl").exists():
            raise ValueError("新源码树已存在下载目录，需要核对共享下载方式")
        (tree / "dl").symlink_to(downloads, target_is_directory=True)
        subprocess.run(["bash", str(ROOT / "scripts/build.sh"), str(tree), str(ROOT / "work/logs" / layout)], env=environment, check=True)
        subprocess.run([sys.executable, str(ROOT / "scripts/collect.py"), "--tree", str(tree), "--lock", str(args.lock.resolve()), "--profile", str(args.profile.resolve()), "--layout", layout, "--output", str(ROOT / "work" / ("delivery-" + layout))], env=environment, check=True)
        # 仅删除本脚本固定的临时树；第一种镜像与日志已保存在 work 下。
        shutil.rmtree(tree)
        print("::endgroup::", flush=True)
    print("两种分区镜像均已编译并通过各自的交付检查。")


if __name__ == "__main__":
    main_guard(main)
