#!/usr/bin/env bash
# GitHub 编译日志保留在 Actions；不上传固件 Artifact。
set -euo pipefail
tree="$1"
log_dir="$2"
mkdir -p "$log_dir"
cd "$tree"
make download -j8 || make download -j1 V=s
set +e
make -j"$(nproc)" V=s 2>&1 | tee "$log_dir/并行编译.log"
build_status="${PIPESTATUS[0]}"
if [ "$build_status" -ne 0 ]; then
	echo "并行编译失败，使用单线程重试并输出明确错误。"
	make -j1 V=s 2>&1 | tee "$log_dir/单线程编译.log"
	build_status="${PIPESTATUS[0]}"
fi
exit "$build_status"
