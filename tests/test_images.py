"""验证镜像检查能拒绝错误设备、双系统分区和校准分区变化。"""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from images import parse_fdt, same_squashfs, ubi_volumes, validate_ap8220_fit


def fdt(nodes):
    tree = {"properties": {}, "children": {}}
    for path, properties in nodes.items():
        node = tree
        for part in path.strip("/").split("/") if path != "/" else []:
            node = node["children"].setdefault(part, {"properties": {}, "children": {}})
        node["properties"] = properties
    strings = bytearray()
    offsets = {}
    structure = bytearray()

    def token(value):
        structure.extend(struct.pack(">I", value))

    def write(name, node):
        token(1)
        structure.extend(name.encode() + b"\0")
        structure.extend(b"\0" * (-len(structure) % 4))
        for key, value in node["properties"].items():
            if key not in offsets:
                offsets[key] = len(strings)
                strings.extend(key.encode() + b"\0")
            token(3)
            structure.extend(struct.pack(">II", len(value), offsets[key]))
            structure.extend(value)
            structure.extend(b"\0" * (-len(structure) % 4))
        for key, value in node["children"].items():
            write(key, value)
        token(2)
    write("", tree)
    token(9)
    start = 56
    string_start = start + len(structure)
    total = string_start + len(strings)
    header = struct.pack(">10I", 0xD00DFEED, total, start, string_start, 40, 17, 16, 0, len(strings), len(structure))
    return header + b"\0" * 16 + bytes(structure) + bytes(strings)


def ap_nodes():
    return {
        "/": {"compatible": b"aliyun,ap8220\0qcom,ipq8074\0"},
        "/soc/nand-controller/nand@0/partitions/partition@0": {
            "label": b"rootfs\0", "reg": struct.pack(">II", 0, 0),
        },
        "/soc/spi/flash@0/partitions/partition@300000": {
            "label": b"0:art\0", "reg": struct.pack(">II", 0x300000, 0x40000), "read-only": b"",
        },
    }


def fit(nodes):
    return fdt({"/images/fdt@1": {"type": b"flat_dt\0", "compression": b"none\0", "data": fdt(nodes)}})


class ImageTests(unittest.TestCase):
    def test_squashfs_different_container_padding_is_allowed(self):
        filesystem = bytearray(100)
        filesystem[:4] = b"hsqs"
        struct.pack_into("<Q", filesystem, 40, len(filesystem))
        self.assertTrue(same_squashfs(bytes(filesystem) + b"\0" * 20, bytes(filesystem) + b"\xff" * 80))

    def test_squashfs_actual_data_difference_is_rejected(self):
        left = bytearray(100)
        left[:4] = b"hsqs"
        struct.pack_into("<Q", left, 40, len(left))
        right = left.copy()
        right[99] = 1
        self.assertFalse(same_squashfs(left, right))

    def test_single_rootfs_fit(self):
        validate_ap8220_fit(fit(ap_nodes()))

    def test_dual_rootfs_is_rejected(self):
        nodes = ap_nodes()
        nodes["/soc/nand-controller/nand@0/partitions/partition@3000000"] = {"label": b"rootfs2\0"}
        with self.assertRaises(ValueError):
            validate_ap8220_fit(fit(nodes))

    def test_wrong_board_is_rejected(self):
        nodes = ap_nodes()
        nodes["/"]["compatible"] = b"other,board\0"
        with self.assertRaises(ValueError):
            validate_ap8220_fit(fit(nodes))

    def test_art_changes_are_rejected(self):
        nodes = ap_nodes()
        nodes["/soc/spi/flash@0/partitions/partition@300000"].pop("read-only")
        with self.assertRaises(ValueError):
            validate_ap8220_fit(fit(nodes))

    def test_truncated_fdt_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_fdt(fit(ap_nodes())[:-8])

    def test_invalid_factory_is_rejected(self):
        with self.assertRaises(ValueError):
            ubi_volumes(b"\0" * (128 * 1024))
