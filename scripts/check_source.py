#!/usr/bin/env python3
"""源码交付检查：版本、配置、语法、工作流和文件数量。"""
import ast
import shutil
import subprocess
from apbuild import ROOT, config_values, main_guard, read_json, validate_profile, version
from boot_assets import check_assets
from footstrap import validate_translation


def main():
    source_version = version()
    check_assets()
    validate_translation((ROOT / "config/footstrap.zh-cn.po").read_text())
    validate_profile(read_json(ROOT / "config/ap-defaults.json"))
    config_values((ROOT / "config/ap8220-ap.config").read_text())
    files = [
        path for path in ROOT.rglob("*") if path.is_file()
        and not any(part in {".git", "openwrt", "work", "release", ".cache", "__pycache__"} for part in path.relative_to(ROOT).parts)
        and path.suffix not in {".pyc", ".zip", ".log"}
    ]
    if len(files) > 100:
        raise ValueError("项目源码文件超过 100 个")
    shells = []
    for path in files:
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        first = path.read_bytes()[:64]
        if first.startswith(b"#!/bin/sh") or first.startswith(b"#!/usr/bin/env bash"):
            shell = "bash" if first.startswith(b"#!/usr/bin/env bash") else "sh"
            subprocess.run([shell, "-n", str(path)], check=True)
            shells.append(path)
    if shutil.which("shellcheck"):
        subprocess.run(
            ["shellcheck", "-e", "SC1091,SC2034", *map(str, shells)], check=True,
        )
    import yaml
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(workflow.get("jobs"), dict):
            raise ValueError("工作流缺少 jobs")
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                action = step.get("uses", "")
                if action and not __import__("re").fullmatch(r"actions/(checkout|cache)@[0-9a-f]{40}", action):
                    raise ValueError(f"Action 必须锁定已核对的提交：{action}")
                if "upload-artifact" in action:
                    raise ValueError("本项目不上传固件到 Artifacts")
    for name in ("README.md", "CHANGELOG.md"):
        if f"v{source_version}" not in (ROOT / name).read_text(encoding="utf-8"):
            raise ValueError(f"{name} 缺少当前源码版本")
    print(f"源码 v{source_version} 检查通过，共 {len(files)} 个文件。")


if __name__ == "__main__":
    main_guard(main)
