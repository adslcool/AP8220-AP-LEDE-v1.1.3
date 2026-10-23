# AP8220 128MiB 大分区启动资料 v1.0.0

已附：

- uboot-ipq807x-aliyun_ap8220-260816_142236_3011049.bin：chenxin527 固定发布版本 26.08.16-14.22.36-3011049，655360 字节。
- ap8220-large128-mibib.bin：用户提供的 mibib.bin，65536 字节；NAND 单 rootfs，起始块 0、长度 0x400 个 128KiB 块，共 128MiB。

U-Boot 字节数与 SHA256 已和作者 Release 资产元数据核对。MIBIB 已检查完整分区表，SPI 前 14 个分区记录与本包原厂布局分区表一致。尚未执行设备刷写验证。

来源、版本、哈希及逐项分区信息见根目录“来源与检查记录.json”。第三方 U-Boot 保留原作者版权，源码与使用说明见：

https://github.com/chenxin527/uboot-qsdk12.5-build/releases/tag/26.08.16-14.22.36-3011049

首次刷写步骤见根目录 README.md：先备份，按需更新 U-Boot、MIBIB，重新进入 Web 核验单 rootfs，再刷 large128 的 factory.ubi。NAND 的 sysupgrade.bin 留给已经启动的 LEDE / OpenWrt 内升级。

已使用匹配 Web U-Boot 与 128MiB 分区的设备，正常升级不必重刷本目录文件。
