#!/usr/bin/env python3
"""校验 FIT/DTB 与 UBI；只读解析，不执行刷写操作。"""
from __future__ import annotations

import binascii
import gzip
import struct
import zlib


def be32(data, offset=0):
    if offset < 0 or offset + 4 > len(data):
        raise ValueError("镜像数据截断")
    return struct.unpack_from(">I", data, offset)[0]


def fit_data(image, props):
    if "data" in props:
        return props["data"]
    size = be32(props.get("data-size", b""))
    if "data-position" in props:
        offset = be32(props["data-position"])
    else:
        offset = ((be32(image, 4) + 3) & ~3) + be32(props.get("data-offset", b""))
    if offset < be32(image, 4) or offset + size > len(image):
        raise ValueError("FIT 外部数据截断或指向头部")
    return image[offset:offset + size]


def same_squashfs(left: bytes, right: bytes) -> bool:
    """比较文件系统实际长度；tar 的零填充与 UBI 的 FF 填充可以不同。"""
    if min(len(left), len(right)) < 96 or left[:4] != b"hsqs" or right[:4] != b"hsqs":
        return False
    left_used = struct.unpack_from("<Q", left, 40)[0]
    right_used = struct.unpack_from("<Q", right, 40)[0]
    if left_used != right_used or not 96 <= left_used <= min(len(left), len(right)):
        return False
    return left[:left_used] == right[:right_used]


def parse_fdt(data: bytes) -> dict[str, dict[str, bytes]]:
    if len(data) < 40 or be32(data) != 0xD00DFEED:
        raise ValueError("缺少有效的 FIT/设备树头部")
    total, start, strings_start = be32(data, 4), be32(data, 8), be32(data, 12)
    strings_size, structure_size = be32(data, 32), be32(data, 36)
    if total > len(data) or start + structure_size > total or strings_start + strings_size > total:
        raise ValueError("FIT/设备树长度不合法")
    strings = data[strings_start:strings_start + strings_size]
    position, end = start, start + structure_size
    stack, nodes = [], {}
    while position < end:
        token = be32(data, position)
        position += 4
        if token == 1:
            zero = data.find(b"\0", position, end)
            if zero < 0:
                raise ValueError("设备树节点名称未结束")
            name = data[position:zero].decode("ascii")
            stack.append(name)
            nodes["/" + "/".join(stack[1:])] = {}
            position = (zero + 4) & ~3
        elif token == 2:
            if not stack:
                raise ValueError("设备树层级无效")
            stack.pop()
        elif token == 3:
            length, name_offset = be32(data, position), be32(data, position + 4)
            position += 8
            if not stack or name_offset >= len(strings) or position + length > end:
                raise ValueError("设备树属性越界")
            zero = strings.find(b"\0", name_offset)
            if zero < 0:
                raise ValueError("设备树属性名称未结束")
            name = strings[name_offset:zero].decode("ascii")
            nodes["/" + "/".join(stack[1:])][name] = data[position:position + length]
            position = (position + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            if stack:
                raise ValueError("设备树节点未正常关闭")
            return nodes
        else:
            raise ValueError(f"设备树令牌无效：{token}")
    raise ValueError("设备树缺少结束标记")


def validate_ap8220_fit(kernel: bytes, layout="large128", require_layout_marker=False) -> None:
    fit = parse_fdt(kernel)
    trees = []
    for path, props in fit.items():
        if not path.startswith("/images/") or props.get("type", b"").rstrip(b"\0") != b"flat_dt":
            continue
        blob = fit_data(kernel, props)
        compression = props.get("compression", b"none\0").rstrip(b"\0")
        if compression == b"gzip":
            blob = gzip.decompress(blob)
        elif compression != b"none":
            raise ValueError("尚未支持的设备树压缩格式")
        nodes = parse_fdt(blob)
        if b"aliyun,ap8220" in nodes.get("/", {}).get("compatible", b"").split(b"\0"):
            trees.append(nodes)
    if len(trees) != 1:
        raise ValueError("FIT 中必须包含唯一的 AP8220 设备树")
    nodes = trees[0]
    labels = {
        path: props.get("label", b"").rstrip(b"\0").decode("ascii", errors="strict")
        for path, props in nodes.items()
    }
    marker = nodes["/"].get("ap8220,flash-layout", b"").rstrip(b"\0").decode("ascii")
    if require_layout_marker and marker != layout:
        raise ValueError("实际设备树缺少匹配的布局标记")
    nand = {label: nodes[path].get("reg") for path, label in labels.items() if "/nand@0/" in path and label in {"rootfs", "rootfs1", "rootfs2", "usrdata"}}
    if layout == "large128":
        if set(nand) != {"rootfs"} or nand["rootfs"] not in {struct.pack(">II", 0, 0), struct.pack(">II", 0, 0x8000000)}:
            raise ValueError("镜像中的 NAND rootfs 不符合 128MiB 单分区要求")
    elif layout == "stock":
        expected = {"rootfs1": struct.pack(">II", 0, 0x3000000), "rootfs2": struct.pack(">II", 0x3000000, 0x3000000), "usrdata": struct.pack(">II", 0x6000000, 0x2000000)}
        if nand != expected:
            raise ValueError("镜像中的 NAND 分区不符合原厂 48+48+32MiB 布局")
    else:
        raise ValueError("未知分区布局")
    art = [nodes[path] for path, label in labels.items() if label == "0:art"]
    if len(art) != 1 or art[0].get("reg") != struct.pack(">II", 0x300000, 0x40000) or "read-only" not in art[0]:
        raise ValueError("镜像中的原厂 ART 校准分区定义发生变化")
    return nodes


def validate_stock_boot(image: bytes):
    """按原厂 boot4 的 0x42000000 暂存地址检查解压和保留内存范围。"""
    nodes = validate_ap8220_fit(image, "stock", True)
    fit = parse_fdt(image)
    kernels = [(path, props) for path, props in fit.items() if path.startswith("/images/") and props.get("type") == b"kernel\0"]
    if len(kernels) != 1:
        raise ValueError("原厂启动 FIT 必须包含唯一内核")
    path, props = kernels[0]
    if props.get("arch") != b"arm64\0" or props.get("compression") != b"gzip\0":
        raise ValueError("原厂启动只接受已适配的 ARM64 gzip 内核")
    load = int.from_bytes(props.get("load", b""), "big")
    entry = int.from_bytes(props.get("entry", b""), "big")
    if len(props.get("load", b"")) not in (4, 8) or len(props.get("entry", b"")) not in (4, 8) or entry != load:
        raise ValueError("原厂启动内核的加载地址或入口格式无效")
    configuration = fit.get("/configurations/config@ac02", {})
    if configuration.get("kernel", b"").rstrip(b"\0").decode() != path.rsplit("/", 1)[1]:
        raise ValueError("原厂 config@ac02 未引用被检查的内核")
    fdt_name = configuration.get("fdt", b"").rstrip(b"\0").decode()
    if fit.get("/images/" + fdt_name, {}).get("type") != b"flat_dt\0":
        raise ValueError("原厂 config@ac02 未引用有效设备树")
    chosen = fit["/images/" + fdt_name]
    blob = fit_data(image, chosen)
    if chosen.get("compression", b"none\0") == b"gzip\0":
        blob = gzip.decompress(blob)
    if parse_fdt(blob) != nodes:
        raise ValueError("原厂 config@ac02 引用的设备树与被检查设备树不同")
    compressed = fit_data(image, props)
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        raw = decoder.decompress(compressed, 96 * 1024 * 1024 + 1)
    except zlib.error as error:
        raise ValueError("原厂启动内核 gzip 校验失败") from error
    if not decoder.eof or decoder.unused_data or len(raw) > 96 * 1024 * 1024:
        raise ValueError("原厂启动解压内核超过内存预算或 gzip 不完整")
    if len(raw) < 64 or raw[56:60] != b"ARM\x64":
        raise ValueError("解压后不是有效的 ARM64 Image")
    declared = struct.unpack_from("<Q", raw, 16)[0]
    if not declared:
        raise ValueError("ARM64 Image 未声明运行内存大小")
    end = load + max(len(raw), declared)
    source, source_end = 0x42000000, 0x42000000 + len(image)
    if source < end and load < source_end:
        raise ValueError("原厂启动：FIT 暂存区与解压内核重叠")
    if load != 0x44000000:
        raise ValueError("原厂启动内核加载地址未适配为 0x44000000")
    # 保守窗口低于上游 TZ/U-Boot 保留区，另按实际 DTB 检查全部固定保留区。
    if source_end > 0x44000000 or end > 0x4A000000:
        raise ValueError("原厂启动镜像超过固定内存安全窗口")
    parent = nodes.get("/reserved-memory", {})
    ac = be32(parent.get("#address-cells", struct.pack(">I", 2)))
    sc = be32(parent.get("#size-cells", struct.pack(">I", 2)))
    if ac not in (1, 2) or sc not in (1, 2):
        raise ValueError("不支持的保留内存单元格式")
    for name, region in nodes.items():
        if not name.startswith("/reserved-memory/") or region.get("status") == b"disabled\0" or "reg" not in region:
            continue
        reg, stride = region["reg"], (ac + sc) * 4
        if not reg or len(reg) % stride:
            raise ValueError("保留内存范围定义无效")
        for offset in range(0, len(reg), stride):
            start = int.from_bytes(reg[offset:offset + ac * 4], "big")
            size = int.from_bytes(reg[offset + ac * 4:offset + stride], "big")
            if size and any(left < start + size and start < right for left, right in ((source, source_end), (load, end))):
                raise ValueError("原厂启动镜像占用了保留内存：" + name)
    return {"FIT暂存地址": hex(source), "FIT长度": len(image), "内核解压地址": hex(load), "内核解压长度": len(raw), "内核运行内存长度": declared, "检查上界": hex(end)}


def ubi_volumes(data: bytes) -> dict[str, bytes]:
    peb_size = 128 * 1024
    if not data or len(data) % peb_size or len(data) > 128 * 1024 * 1024:
        raise ValueError("Factory UBI 大小或擦除块对齐不符合 AP8220 要求")
    blocks, table = {}, None
    for position in range(0, len(data), peb_size):
        block = data[position:position + peb_size]
        if block[:4] != b"UBI#":
            raise ValueError("Factory 文件不是标准 UBI 镜像")
        if be32(block, 60) != (binascii.crc32(block[:60]) ^ 0xFFFFFFFF):
            raise ValueError("UBI 擦除计数头部校验失败")
        vid_offset, data_offset = be32(block, 16), be32(block, 20)
        if vid_offset != 2048 or data_offset != 4096:
            raise ValueError("UBI 页大小不符合 AP8220 的 2048 字节要求")
        vid = block[vid_offset:vid_offset + 64]
        if vid[:4] == b"\xff" * 4:
            continue
        if vid[:4] != b"UBI!" or be32(vid, 60) != (binascii.crc32(vid[:60]) ^ 0xFFFFFFFF):
            raise ValueError("UBI 卷头部校验失败")
        volume, logical = be32(vid, 8), be32(vid, 12)
        if volume == 0x7FFFEFFF:
            table = block[data_offset:]
            continue
        payload = block[data_offset:]
        if vid[5] == 2:
            payload = payload[:be32(vid, 20)]
        if logical in blocks.setdefault(volume, {}):
            raise ValueError("Factory UBI 中存在重复的逻辑块")
        blocks[volume][logical] = payload
    if table is None:
        raise ValueError("Factory UBI 缺少卷表")
    names = {}
    for volume in range(min(128, len(table) // 172)):
        record = table[volume * 172:(volume + 1) * 172]
        if be32(record) == 0:
            continue
        length = struct.unpack_from(">H", record, 14)[0]
        if not 0 < length <= 127:
            continue
        name = record[16:16 + length].decode("ascii")
        if volume in blocks:
            ordered = blocks[volume]
            if sorted(ordered) != list(range(len(ordered))):
                raise ValueError("Factory UBI 中存在缺失的逻辑块")
            names[name] = b"".join(ordered[i] for i in range(len(ordered)))
    return names
