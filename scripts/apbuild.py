#!/usr/bin/env python3
"""AP8220 AP 专用固件：构建、版本、配置与交付的公共函数。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LEAN_URL = "https://github.com/coolsnowwolf/lede.git"
UPSTREAM_PACKAGES_URL = "https://github.com/openwrt/packages.git"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def version() -> str:
    value = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("VERSION 必须使用三段版本号，例如 1.0.0")
    return value


def run(args: list[str], cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(
        args, cwd=cwd, check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "AP8220-AP/1.1.3"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read().decode("utf-8")


def resolve_git(url: str, ref: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", ref) or ".." in ref:
        raise ValueError("源码分支或提交参数无效")
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref
    refs = ["HEAD"] if ref == "HEAD" else [
        f"refs/heads/{ref}", f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}"
    ]
    result = run(["git", "ls-remote", url, *refs], capture=True)
    values = {}
    for line in result.splitlines():
        sha, name = line.split()
        values[name] = sha
    for name in reversed(refs):
        if name in values and re.fullmatch(r"[0-9a-f]{40}", values[name]):
            return values[name]
    raise ValueError(f"无法解析上游版本：{url}，{ref}")


def parse_feeds(text: str) -> list[dict]:
    """保留 Lean 指定的分支；AP 版本不启用代理与电话软件源。"""
    feeds = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 3 or fields[0] not in {"src-git", "src-git-full"}:
            raise ValueError(f"发现尚未支持的软件源格式，需要人工适配：{line}")
        method, name, location = fields
        if name in {"helloworld", "telephony"}:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError("软件源名称无效")
        url, separator, branch = location.partition(";")
        if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", url):
            raise ValueError(f"不支持的软件源地址：{url}")
        feeds.append({"method": method, "name": name, "url": url, "ref": branch if separator else "HEAD"})
    if not {"packages", "luci"} <= {entry["name"] for entry in feeds}:
        raise ValueError("缺少 packages 或 luci 软件源")
    if len({entry["name"] for entry in feeds}) != len(feeds):
        raise ValueError("软件源名称重复")
    return feeds


def config_values(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        match = re.fullmatch(r"(CONFIG_[A-Za-z0-9_-]+)=(.*)", line)
        disabled = re.fullmatch(r"# (CONFIG_[A-Za-z0-9_-]+) is not set", line)
        if match:
            key, value = match.groups()
        elif disabled:
            key, value = disabled.group(1), "n"
        else:
            continue
        if key in values:
            raise ValueError(f"配置项重复：{key}")
        values[key] = value
    return values


def check_config(text: str, policy: dict) -> None:
    values = config_values(text)
    missing = [name for name in policy["required"] if values.get(f"CONFIG_PACKAGE_{name}") != "y"]
    extra = [name for name in policy["forbidden"] if values.get(f"CONFIG_PACKAGE_{name}") in {"y", "m"}]
    flags = [name for name in policy["required_flags"] if values.get(name) != "y"]
    devices = [
        key for key, value in values.items()
        if key.startswith("CONFIG_TARGET_qualcommax_ipq807x_DEVICE_") and value == "y"
    ]
    if devices != ["CONFIG_TARGET_qualcommax_ipq807x_DEVICE_aliyun_ap8220"]:
        raise ValueError(f"设备目标必须仅包含 AP8220：{devices}")
    if missing or extra or flags:
        raise ValueError(f"配置检查失败；缺少包：{missing}；禁止包：{extra}；缺少选项：{flags}")


def validate_profile(profile: dict) -> None:
    for key in ("ssid_2g", "ssid_5g"):
        value = profile[key]
        if not isinstance(value, str) or not 1 <= len(value.encode("utf-8")) <= 32:
            raise ValueError(f"{key} 必须为 1—32 字节")
        if any(ord(ch) < 32 or ch in "'\\" for ch in value):
            raise ValueError(f"{key} 不能包含控制字符、单引号或反斜杠")
    password = profile["wifi_password"]
    if not isinstance(password, str) or not 8 <= len(password) <= 63 or not password.isascii():
        raise ValueError("无线密码须为 8—63 个 ASCII 字符")
    if any(ord(ch) < 32 or ch in "'\\" for ch in password):
        raise ValueError("无线密码不能包含控制字符、单引号或反斜杠")
    if not isinstance(profile["root_password"], str) or not profile["root_password"] or any(
        ch in profile["root_password"] for ch in "\r\n\0"
    ):
        raise ValueError("root 密码不能为空或包含换行、空字符")
    if not re.fullmatch(r"[A-Z]{2}|00", profile["country"]):
        raise ValueError("国家码无效")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,31}", profile["hostname_prefix"]):
        raise ValueError("主机名前缀无效")
    for key in ("mobility_domain_2g", "mobility_domain_5g"):
        if not re.fullmatch(r"[0-9a-fA-F]{4}", profile[key]):
            raise ValueError("移动域必须为四位十六进制")
    if profile["ssid_2g"] == profile["ssid_5g"] and profile["mobility_domain_2g"] != profile["mobility_domain_5g"]:
        raise ValueError("统一 SSID 时两个频段应使用相同的移动域")
    for key in ("channel_2g", "channel_5g"):
        if not re.fullmatch(r"auto|[1-9][0-9]{0,2}", str(profile[key])):
            raise ValueError("信道须为 auto 或正整数")
    if profile["htmode_2g"] not in {"HE20", "HT20"} or profile["htmode_5g"] not in {"HE80", "VHT80", "HE40", "HE20"}:
        raise ValueError("无线带宽参数无效")
    if not isinstance(profile["ieee80211r"], bool):
        raise ValueError("ieee80211r 必须为布尔值")
    for key in ("timezone", "zonename"):
        if not re.fullmatch(r"[A-Za-z0-9_+:/-]+", profile[key]):
            raise ValueError("时区参数无效")


def replace_router_defaults(text: str) -> str:
    pattern = r"(?m)^DEFAULT_PACKAGES\.router:=\\\n(?:.*\\\n)*[^\n]*\n"
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise ValueError("Lean 默认软件包定义发生变化，需要人工适配，停止构建")
    return re.sub(
        pattern,
        lambda _: "DEFAULT_PACKAGES.router:=\\\n\tfirewall4 nftables-json odhcp6c ip-full ca-certificates\n",
        text, count=1,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main_guard(function) -> None:
    try:
        function()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"错误：{error}") from error
