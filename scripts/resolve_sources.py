#!/usr/bin/env python3
"""解析最新上游并生成本次构建的不可变版本锁。"""
import argparse
from datetime import datetime
import hashlib
import os
from zoneinfo import ZoneInfo
from apbuild import (
    ROOT, LEAN_URL, UPSTREAM_PACKAGES_URL, fetch_text, main_guard,
    parse_feeds, resolve_git, version, write_json,
    read_json,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lean-ref", default="master")
    parser.add_argument("--output", type=__import__("pathlib").Path, required=True)
    args = parser.parse_args()
    lean_sha = resolve_git(LEAN_URL, args.lean_ref)
    feed_text = fetch_text(f"https://raw.githubusercontent.com/coolsnowwolf/lede/{lean_sha}/feeds.conf.default")
    feeds = parse_feeds(feed_text)
    for entry in feeds:
        entry["commit"] = resolve_git(entry["url"], entry["ref"])
    recipe_commit = resolve_git(UPSTREAM_PACKAGES_URL, "master")
    recipe_url = f"https://raw.githubusercontent.com/openwrt/packages/{recipe_commit}/net/usteer/Makefile"
    recipe = fetch_text(recipe_url)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    sequence = os.environ.get("GITHUB_RUN_NUMBER", "local")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    build_code = f"R{now:%y.%m.%d}-b{sequence}.{attempt}"
    lock = {
        "schema": 1,
        "source_version": version(),
        "firmware_version": f"v{version()}-{build_code}",
        "build_code": build_code,
        "built_at": now.isoformat(timespec="seconds"),
        "build_repository": os.environ.get("GITHUB_REPOSITORY", "本地源码包"),
        "build_commit": os.environ.get("GITHUB_SHA", "本地源码包"),
        "workflow_run": (
            f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
            if os.environ.get("GITHUB_RUN_ID") else ""
        ),
        "lean": {"url": LEAN_URL, "ref": args.lean_ref, "commit": lean_sha},
        "feeds": feeds,
        "footstrap": read_json(ROOT / "config/footstrap-source.json"),
        "usteer_recipe": {
            "url": recipe_url, "repository": UPSTREAM_PACKAGES_URL,
            "commit": recipe_commit,
            "sha256": hashlib.sha256(recipe.encode("utf-8")).hexdigest(),
        },
    }
    write_json(args.output, lock)
    if os.environ.get("GITHUB_OUTPUT"):
        # 缓存键只跟源码输入变化，不把日期和运行号算入缓存指纹。
        import json
        fingerprint = hashlib.sha256(json.dumps({
            "lean": lean_sha,
            "feeds": [(entry["name"], entry["commit"]) for entry in feeds],
            "usteer": recipe_commit,
            "footstrap": lock["footstrap"]["commit"],
        }, sort_keys=True).encode()).hexdigest()[:20]
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write(f"cache_key={fingerprint}\n")
    print(f"源码版本：v{version()}\n固件版本：{lock['firmware_version']}\nLean 提交：{lean_sha}")


if __name__ == "__main__":
    main_guard(main)
