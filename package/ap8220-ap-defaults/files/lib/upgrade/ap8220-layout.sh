#!/bin/sh
# shellcheck shell=ash
# AP8220 升级前核验当前 NAND 布局和镜像元数据；不写启动分区。

ap8220_current_layout() {
    awk '
        $4 == "\"rootfs\"" && $2 == "08000000" { large++ }
        $4 == "\"rootfs1\"" && $2 == "03000000" { one++ }
        $4 == "\"rootfs2\"" && $2 == "03000000" { two++ }
        $4 == "\"usrdata\"" && $2 == "02000000" { data++ }
        END {
            if (large == 1 && !one && !two && !data) print "large128"
            else if (!large && one == 1 && two == 1 && data == 1) print "stock"
        }
    ' /proc/mtd
}

ap8220_stock_partition() {
    local active
    active="$(fw_printenv -n active)" || {
        echo 'AP8220：无法可靠读取原厂 active，停止升级并检查启动环境。' >&2
        return 1
    }
    case "$active" in
        1) echo rootfs1 ;;
        2) echo rootfs2 ;;
        *) echo 'AP8220：原厂 active 不是 1 或 2，停止升级并检查启动环境。' >&2; return 1 ;;
    esac
}

ap8220_check_layout() {
    local actual compiled image_layout metadata
    actual="$(ap8220_current_layout)"
    compiled="$(sed -n 's/^FLASH_LAYOUT=//p' /etc/ap8220-ap-release | tr -d "'\"")"
    if [ -z "$actual" ] || [ "$actual" != "$compiled" ]; then
        echo 'AP8220：当前分区与本机固件布局不一致，停止升级。' >&2
        return 1
    fi
    metadata="$(mktemp /tmp/ap8220-upgrade.XXXXXX)" || return 1
    if ! fwtool -q -i "$metadata" "$1"; then
        rm -f "$metadata"
        echo 'AP8220：无法读取镜像布局元数据。' >&2
        return 1
    fi
    image_layout="$(jsonfilter -i "$metadata" -e '@.ap8220_layout')"
    rm -f "$metadata"
    if [ "$image_layout" != "$actual" ]; then
        echo 'AP8220：镜像缺少匹配的布局标记，禁止普通升级跨布局刷写。' >&2
        return 1
    fi
    if [ "$actual" = stock ]; then
        ap8220_stock_partition >/dev/null || return 1
    fi
}

ap8220_do_upgrade() {
    # 再次检查，避免强制升级参数绕过布局匹配。
    ap8220_check_layout "$1" || return 1
    case "$(ap8220_current_layout)" in
        large128) CI_UBIPART=rootfs ;;
        stock)
            CI_UBIPART="$(ap8220_stock_partition)" || return 1
            ;;
        *) return 1 ;;
    esac
    nand_do_upgrade "$1"
}
