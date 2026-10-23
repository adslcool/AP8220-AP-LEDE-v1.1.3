"""AP8220 两种布局的构建适配；保持所有上游无线与 NSS 定义。"""
from pathlib import Path
import re

LAYOUTS = {
    "stock": {"title": "原厂分区", "limit": 44 * 1024 * 1024},
    "large128": {"title": "128MiB 大分区", "limit": 120 * 1024 * 1024},
}


def adapt_dts(text, layout):
    if layout not in LAYOUTS:
        raise ValueError("未知分区布局")
    if any(f'label = "{name}";' in text for name in ("rootfs1", "rootfs2", "usrdata")):
        raise ValueError("上游 AP8220 分区结构已变化，停止自动适配")
    pattern = r'partition@0\s*\{\s*label = "rootfs";\s*reg = <0x0\s+0x0>;\s*\};'
    if len(re.findall(pattern, text)) != 1:
        raise ValueError("找不到唯一的上游单 rootfs 定义")
    if layout == "stock":
        text = re.sub(pattern, '''partition@0 {
                label = "rootfs1";
                reg = <0x0 0x3000000>;
            };
            partition@3000000 {
                label = "rootfs2";
                reg = <0x3000000 0x3000000>;
            };
            partition@6000000 {
                label = "usrdata";
                reg = <0x6000000 0x2000000>;
            };''', text, count=1)
    if text.count('model = "Aliyun AP8220";') != 1:
        raise ValueError("AP8220 设备型号定义不唯一")
    return text.replace('model = "Aliyun AP8220";', 'model = "Aliyun AP8220";\n\tap8220,flash-layout = "' + layout + '";', 1)


def adapt_image_makefile(text, layout):
    if layout not in LAYOUTS:
        raise ValueError("未知分区布局")
    pattern = r'(?ms)^define Device/aliyun_ap8220\n.*?^endef$'
    blocks = re.findall(pattern, text)
    if len(blocks) != 1 or "IMAGE_METADATA" in blocks[0]:
        raise ValueError("上游 AP8220 镜像定义发生变化，需要复核")
    block = blocks[0].replace("\nendef", '\n\tIMAGE_METADATA := "ap8220_layout": "' + layout + '"\nendef')
    if layout == "stock":
        if "KERNEL_LOADADDR" in block:
            raise ValueError("上游 AP8220 已有专用加载地址，需要复核")
        block = block.replace("\nendef", "\n\tKERNEL_LOADADDR := 0x44000000\nendef")
    return text.replace(blocks[0], block, 1)


def adapt_platform(text):
    check = 'platform_check_image() {\n\treturn 0;\n}'
    group = 'aliyun,ap8220|\\\n'
    switch = 'case "$(board_name)" in\n'
    if text.count(check) != 1 or text.count(group) != 1 or text.count(switch) != 1:
        raise ValueError("上游 AP8220 升级脚本结构发生变化，需要复核")
    text = text.replace(group, "", 1)
    text = text.replace(check, '''platform_check_image() {
    [ "$(board_name)" != "aliyun,ap8220" ] || ap8220_check_layout "$1"
}''', 1)
    text = text.replace(switch, switch + '''    aliyun,ap8220)
        ap8220_do_upgrade "$1"
        ;;
''', 1)
    return text + '''
# 布局检查同时在写入前执行，正常升级不修改启动程序或 MIBIB。
RAMFS_COPY_BIN="$RAMFS_COPY_BIN fwtool jsonfilter mktemp tr"
RAMFS_COPY_DATA="$RAMFS_COPY_DATA /lib/upgrade/ap8220-layout.sh /etc/ap8220-ap-release"
. /lib/upgrade/ap8220-layout.sh
'''


def adapt_tree(tree: Path, layout):
    dts = tree / "target/linux/qualcommax/dts/ipq8071-ap8220.dts"
    dts.write_text(adapt_dts(dts.read_text(), layout), encoding="utf-8")
    image = tree / "target/linux/qualcommax/image/ipq807x.mk"
    image.write_text(adapt_image_makefile(image.read_text(), layout), encoding="utf-8")
    platform = tree / "target/linux/qualcommax/ipq807x/base-files/lib/upgrade/platform.sh"
    platform.write_text(adapt_platform(platform.read_text()), encoding="utf-8")
    envtools = tree / "package/boot/uboot-envtools/files/qualcommax"
    envtools.write_text(adapt_envtools(envtools.read_text()), encoding="utf-8")


def adapt_envtools(text):
    # Lean 的默认表尚未列 AP8220；它使用与 EAP102 相同的 64KiB SPI 环境区。
    if "aliyun,ap8220" in text:
        raise ValueError("上游已增加 AP8220 环境定义，需要复核后再适配")
    group = 'case "$board" in\ncompex,wpq873|\\\n'
    expected = 'ubootenv_add_uci_config "/dev/mtd$idx" "0x0" "0x10000" "0x10000" "1"'
    if text.count(group) != 1 or expected not in text.split('dynalink,dl-wrx36', 1)[0]:
        raise ValueError("上游 U-Boot 环境区定义发生变化，需要复核")
    return text.replace(group, 'case "$board" in\naliyun,ap8220|\\\ncompex,wpq873|\\\n', 1)
