#!/usr/bin/env python3
"""读取编译参数，校验并生成本次构建专用的出厂配置。"""
import argparse
import json
import os
from pathlib import Path

from apbuild import ROOT, main_guard, read_json, validate_profile


def mask_password(value):
    if os.environ.get("GITHUB_ACTIONS") == "true" and value:
        value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::add-mask::" + value, flush=True)


def build_profile(base, environment):
    profile = dict(base)
    for variable, field in (
        ("WIFI_SSID", "ssid_2g"), ("CHANNEL_2G", "channel_2g"),
        ("CHANNEL_5G", "channel_5g"), ("COUNTRY", "country"),
    ):
        if environment.get(variable):
            profile[field] = environment[variable]
    # 工作流的 5GHz 输入留空，表示与本次 2.4GHz SSID 一致。
    profile["ssid_5g"] = environment.get("WIFI_SSID_5G") or profile["ssid_2g"]
    for variable, field in (("WIFI_KEY", "wifi_password"), ("ROOT_PASSWORD", "root_password")):
        profile[field] = environment.get(variable) or environment.get(variable + "_SECRET") or profile[field]
    domain = environment.get("MOBILITY_DOMAIN")
    if domain:
        profile["mobility_domain_2g"] = profile["mobility_domain_5g"] = domain.lower()
    validate_profile(profile)
    return profile


def public_profile(profile):
    return {key: value for key, value in profile.items() if key not in {"root_password", "wifi_password"}}


def write_private_profile(path, profile):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(profile, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=ROOT / "config/ap-defaults.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base = read_json(args.base)
    for variable, field in (("WIFI_KEY", "wifi_password"), ("ROOT_PASSWORD", "root_password")):
        for value in (os.environ.get(variable), os.environ.get(variable + "_SECRET"), base[field]):
            mask_password(value)
    profile = build_profile(base, os.environ)
    write_private_profile(args.output, profile)
    print("本次出厂参数检查通过；管理密码与无线密码不写入构建摘要或发布说明。")


if __name__ == "__main__":
    main_guard(main)
