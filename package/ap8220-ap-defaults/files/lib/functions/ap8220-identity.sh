#!/bin/sh
# shellcheck shell=ash
# 只读本机 product_info；不把运行时地址当作出厂身份。

ap8220_valid_mac() {
    local value first
    value="$(printf '%s' "$1" | tr 'A-F' 'a-f')"
    case "$value" in *[!0-9a-f:]*) return 1 ;; esac
    printf '%s\n' "$value" | grep -Eq '^([0-9a-f]{2}:){5}[0-9a-f]{2}$' || return 1
    [ "$value" != '00:00:00:00:00:00' ] || return 1
    first="${value%%:*}"
    [ "$((0x$first & 1))" -eq 0 ] || return 1
    printf '%s\n' "$value"
}

ap8220_product_mac() {
    local part raw hex
    part="$(awk '$4 == "\"product_info\"" {
        sub(/:$/, "", $1); name=$1; count++; size=$2
    } END { if (count == 1 && size == "00010000") print name }' "$AP_ROOT/proc/mtd")"
    case "$part" in mtd[0-9]*) ;; *) return 1 ;; esac
    [ -r "$AP_ROOT/dev/$part" ] || return 1
    raw="$(dd if="$AP_ROOT/dev/$part" bs=65536 count=1 2>/dev/null | tr '\000' '\n' | sed -n 's/^product\.mac=\{0,1\}//p')"
    hex="$(printf '%s' "$raw" | tr -d ':\r\t -' | tr 'A-F' 'a-f')"
    case "$hex" in *[!0-9a-f]*) return 1 ;; esac
    printf '%s\n' "$hex" | grep -Eq '^[0-9a-f]{12}$' || return 1
    ap8220_valid_mac "$(printf '%s' "$hex" | sed 's/../&:/g;s/:$//')"
}

ap8220_load_identity() {
    local nic oui
    AP_PRODUCT_MAC="$(ap8220_product_mac)" || return 1
    oui="${AP_PRODUCT_MAC%:*:*:*}"
    nic="${AP_PRODUCT_MAC#*:*:*:}"
    nic="$(printf '%s' "$nic" | tr -d ':')"
    nic="$(printf '%06x' "$(((0x$nic + 1) & 0xffffff))" | sed 's/../&:/g;s/:$//')"
    AP_BASE_MAC="$(ap8220_valid_mac "$oui:$nic")" || return 1
}
