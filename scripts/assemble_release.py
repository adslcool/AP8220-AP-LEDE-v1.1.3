#!/usr/bin/env python3
"""将两种已检查固件与各自引导文件组成独立发布包；不接受缺件发布。"""
import argparse
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from apbuild import ROOT, main_guard, read_json, sha256_file, version, write_json
from boot_assets import check_assets
from layouts import LAYOUTS


def write_checksums(directory):
    rows = [f"{sha256_file(path)}  {path.relative_to(directory).as_posix()}" for path in sorted(directory.rglob("*")) if path.is_file() and path != directory / "sha256sums"]
    (directory / "sha256sums").write_text("\n".join(rows) + "\n", encoding="utf-8")


def release_readme(text, layout, firmware_version):
    # 源码交付时的缺项说明不应沿用到已补齐的固件发布包。
    text = re.sub(r"(?s)## 双布局发布与当前缺项\n.*?(?=## 版本号)", "## 本发布包状态\n\n本发布包的固件与对应启动文件均已通过自动检查。原厂 U-Boot 的实际来源见 stock 包内 boot/uboot-info.json；正常系统升级不刷写启动程序或分区表。\n\n", text, count=1)
    text = text.replace("原厂 U-Boot 待补齐", "原厂 U-Boot 已附于 stock 发布包")
    text = text.replace("原厂布局 MIBIB；原厂 U-Boot 补齐后加入", "原厂布局 MIBIB 与经来源核对的原厂 U-Boot")
    text = re.sub(r"本次源码交付时 stock 目录只有结构核对通过的 MIBIB。.*?为准。", "本发布包启动文件齐备，实际交付文件以 boot 目录与发布包信息.json 为准。", text)
    text = text.replace("原厂 U-Boot 补齐并完成版本匹配前，不给出可以直接执行的跨布局恢复写入命令。", "跨布局恢复还需要核对本机启动环境，本教程不提供未经本机核对的通用恢复写入命令。")
    return f"# AP8220 固件 {firmware_version} · {layout}\n\n本包布局：{LAYOUTS[layout]['title']}。boot 目录只适用于该布局。\n\n" + text


def assemble(lock, sources, output):
    check_assets(True)
    if lock["source_version"] != version() or not re.fullmatch(r"v\d+\.\d+\.\d+-R\d{2}\.\d{2}\.\d{2}-b\d+\.\d+", lock["firmware_version"]):
        raise ValueError("正式发布版本锁无效")
    if set(sources) != set(LAYOUTS):
        raise ValueError("必须同时提供两种布局的完整交付目录")
    if output.exists() and any(output.iterdir()):
        raise ValueError("发布目录非空")
    output.mkdir(parents=True, exist_ok=True)
    label = "AP8220-AP-" + lock["firmware_version"]
    for layout, directory in sources.items():
        directory = directory.resolve()
        patterns = ["*-factory.ubi", "*-sysupgrade.bin", "*-源码.zip"]
        if layout == "stock":
            patterns.append("*-initramfs-uImage.itb")
        for pattern in patterns:
            if len(list(directory.glob(pattern))) != 1:
                raise ValueError("发布包缺少唯一的必要文件：" + layout + " " + pattern)
        details = list(directory.glob("*-构建信息.json"))
        if len(details) != 1:
            raise ValueError("缺少唯一的镜像构建信息：" + layout)
        info = read_json(details[0])
        if info.get("布局标记") != layout or info.get("固件版本") != lock["firmware_version"]:
            raise ValueError("交付布局或固件版本不一致")
        # 重新核对 collect 产生的清单，避免整理期间文件被替换。
        for line in (directory / "sha256sums").read_text().splitlines():
            digest, name = line.split("  ", 1)
            target = directory / name
            if not target.resolve().is_relative_to(directory) or sha256_file(target) != digest:
                raise ValueError("已检查交付文件的哈希发生变化")
        with tempfile.TemporaryDirectory(prefix="ap8220-kit-") as temporary:
            stage = Path(temporary) / (label + "-" + layout)
            stage.mkdir()
            for path in directory.iterdir():
                if path.is_file() and path.name != "sha256sums":
                    shutil.copy2(path, stage / path.name)
            shutil.copytree(ROOT / "boot-assets" / layout, stage / "boot")
            (stage / "boot/README.md").write_text(
                f"# AP8220 {layout} 启动文件\n\n本目录仅提供本布局的 U-Boot 与 MIBIB。所有启动文件已通过大小、哈希及分区结构检查；实际来源见发布包信息.json 和启动文件原始来源记录.json。\n\n首次刷写按包根目录 README.md 操作；正常同布局升级不重刷启动文件。不得使用其他设备的 APPSBLENV 或 ART 代替本机备份。\n", encoding="utf-8")
            # 不复制另一布局的引导文件；共同说明记录所有来源和哈希。
            shutil.copy2(ROOT / "boot-assets/来源与检查记录.json", stage / "启动文件原始来源记录.json")
            (stage / "README.md").write_text(release_readme((ROOT / "README.md").read_text(), layout, lock["firmware_version"]), encoding="utf-8")
            write_json(stage / "发布包信息.json", {
                "源码版本": "v" + version(), "固件版本": lock["firmware_version"],
                "布局": layout, "名称": LAYOUTS[layout]["title"],
                "启动文件状态": "完整；正常系统升级不会自动刷写 U-Boot 或 MIBIB",
                "原厂U-Boot来源": read_json(ROOT / "boot-assets/stock/uboot-info.json") if layout == "stock" else None,
                "实机验证": "未由自动构建执行硬件刷入验证",
            })
            write_checksums(stage)
            archive = output / (label + "-" + layout + "-完整发布包.zip")
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
                for path in sorted(stage.rglob("*")):
                    if path.is_file():
                        stream.write(path, path.relative_to(stage.parent).as_posix())
    write_json(output / "发布版本.json", {"源码版本": version(), "固件版本": lock["firmware_version"], "构建时间": lock["built_at"], "布局": list(LAYOUTS)})
    (output / "发布说明.md").write_text(f"# AP8220 双布局固件 {lock['firmware_version']}\n\n分别提供 stock 原厂分区、large128 大分区完整发布包，源码、固件、README、启动文件来源及 SHA256 在各包内。两种镜像均通过各自检查后才发布。\n\n启动文件仅用于相应首次刷写或恢复，正常升级不自动刷 U-Boot 或 MIBIB。实机刷写、NSS 与漫游效果需要设备验收。\n", encoding="utf-8")
    write_checksums(output)
    return label


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    label = assemble(read_json(args.lock), {layout: ROOT / "work" / ("delivery-" + layout) for layout in LAYOUTS}, args.output.resolve())
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write(f"tag={label}\ntitle=AP8220 双布局固件 {label}\n")
    print("两种完整发布包已分别整理，校验通过。")


if __name__ == "__main__":
    main_guard(main)
