#!/usr/bin/env python3
"""构建测试用原生 UCI：使用固定版本的 OpenWrt 官方源码，不安装到系统目录。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import tarfile
import urllib.request

from apbuild import main_guard, run

SOURCES = {
    "libubox": "da2d205a5cf3e877c45a2eec488218cbaf452e7d",
    "uci": "74f6277aabffc943d026f406df57c22595134c42",
}


def download(entry, base):
    name, commit = entry
    archive = base / f"{name}.tar.gz"
    request = urllib.request.Request(
        f"https://codeload.github.com/openwrt/{name}/tar.gz/{commit}",
        headers={"User-Agent": "AP8220-AP-native-test/1.1.3"},
    )
    with urllib.request.urlopen(request, timeout=90) as response, archive.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    with tarfile.open(archive) as stream:
        stream.extractall(base, filter="data")
    return name, base / f"{name}-{commit}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    base = output.parent / "native-uci-sources"
    base.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        sources = dict(pool.map(lambda item: download(item, base), SOURCES.items()))
    output.mkdir(parents=True, exist_ok=True)
    for name in ("libubox", "uci"):
        source = sources[name]
        build = base / f"{name}-build"
        run([
            "cmake", "-S", str(source), "-B", str(build),
            f"-DCMAKE_INSTALL_PREFIX={output}", f"-DCMAKE_PREFIX_PATH={output}",
            "-DCMAKE_INSTALL_LIBDIR=lib", "-DBUILD_LUA=OFF", "-DBUILD_EXAMPLES=OFF",
        ])
        run(["cmake", "--build", str(build), "--parallel", "2"])
        run(["cmake", "--install", str(build)])
    print(f"真实 UCI 测试程序已准备：{output / 'bin/uci'}")


if __name__ == "__main__":
    main_guard(main)
