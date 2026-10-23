# AP8220 原厂布局启动文件 v1.0.1

已附 ap8220-stock-mibib.bin、ap8220-stock-uboot.bin 和 uboot-info.json。

- 分区表：65536 字节，原厂 rootfs1 48MiB、rootfs2 48MiB、usrdata 使用剩余 NAND 空间；本次上传的 1-0-MIBIB(2).bin 与此前收录版本完全一致。
- U-Boot：655360 字节，来自用户上传的 8-0-APPSBL.bin，版本为 U-Boot 2016.01（2020-06-28 12:22:09 +0800），包含原始双槽启动脚本。
- 完整 SHA256、来源、核验范围见 uboot-info.json 与上一层“来源与检查记录.json”。结构与版本符合原厂方案，不等于厂商签名或官方哈希认证。

正常保留原厂布局安装或升级 stock 固件，无须重刷本目录文件。完整刷写教程见项目根目录 README.md。本机 APPSBLENV、ART 与产品数据应另外备份，不使用别机数据覆盖。

源码 v1.1.1 的启动配套完整性检查已通过；整机固件交叉编译与硬件刷入仍待实际验证。
