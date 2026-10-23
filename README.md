# AP8220 AP 专用固件源码 v1.1.3

基于 Lean LEDE 最新源码，为原版阿里云 AP8220 制作的有线回程 AP 专用固件。同时构建原厂布局 stock 与 128MiB NAND 单 rootfs 大分区 large128。两口桥接，管理地址从上级路由器 DHCP 获取。

本项目交付 GitHub Actions 构建源码；编译成功并通过镜像检查后，Actions 自动发布带版本号的固件、对应源码、配置和简体中文说明。

## 默认设置

| 项目 | 默认值 |
| --- | --- |
| 硬件 | 原版 Aliyun AP8220，IPQ8071A，1GiB 内存，128MiB NAND |
| 分区要求 | stock 为 48+48+32MiB；large128 为单 rootfs 128MiB；启动端布局须匹配 |
| 两个有线口 | lan、wan 全部加入 br-lan，端口作用相同 |
| AP 管理 IPv4 | 上级 DHCP 自动分配地址、网关与 DNS |
| IPv6 | 上级 IPv6 桥接通行；AP 自身使用客户端获取管理地址 |
| DHCP/RA 服务端 | 不安装，不向客户端分配地址 |
| 2.4GHz | Home-WiFi，HE20，信道 1；可在编译时修改 |
| 5GHz | Home-WiFi，HE80，信道 36；可在编译时修改 |
| 无线密码 | 12345678 |
| 无线加密 | WPA2-AES，PMF 可选 |
| root 密码 | password |
| 国家码 | CN，可按实际使用地区修改 |
| 管理界面 | 简体中文 LuCI，默认 Footstrap，保留 Argon，HTTP/HTTPS |
| 加速页面 | 保留 Turboacc 中文页面，默认 NSS ECM |
| 漫游 | 完整 wpad-openssl、802.11k/v/r、usteer |
| 漫游域 | a1b2，两个频段与两台 AP 保持一致 |
| 设备标识 | 读取 product_info 出厂 MAC；LAN MAC=出厂地址+1，主机名和 NAS 标识使用固定 LAN 地址 |

不预装 Argon 配置插件、OpenClash、SSR Plus、Xray、Mihomo、Tailscale、ZeroTier、UPnP、DDNS、KMS、FTP 服务、流量统计、定时重启或 DAWN。SFTP 文件传输服务保留。

## 上传与编译

1. 新建自己的 GitHub 仓库。
2. 解压源码包，把文件夹内部的内容上传到仓库根目录。根目录应直接包含 VERSION、README.md、config、scripts、package、tests 和 .github。
3. 上传后，查看 Actions 中的“检查 AP8220 AP 专用固件源码”，确认源码检查通过。
4. 打开“编译并发布 AP8220 AP 专用固件”，点击 Run workflow。
5. lean_ref 保留 master，publish 保留勾选，在表单中填写本次无线与管理参数，然后运行。参数表见下文。
6. 成功后到 Releases 下载各自的完整发布包；失败原因查看 Actions 对应步骤日志。

发布使用 GitHub 自动提供的 GITHUB_TOKEN，不要求填写个人访问令牌。仓库或组织策略需要允许工作流声明的 contents: write 权限。

关闭 publish 仅用于编译验证，不生成可下载的固件交付。固件不会上传至 Actions Artifacts；编译缓存使用 Cache，日志保留在 Actions 页面。

## 双布局发布与启动文件

源码 v1.1.3 已接入一次运行、依次隔离构建 large128 与 stock，共用同一个上游版本锁、编译参数、下载目录和编译缓存。第一种检查通过后释放临时源码树，再编译第二种，避免同时保留两棵大目录。

每种固件分别检查设备树、布局标记、镜像容量、实际配置和包清单；stock 额外交付用于原厂 U-Boot 首次内存启动的 initramfs。原厂系统槽为 48MiB，Factory 镜像预算为 44MiB；大分区预算为 120MiB，均预留 UBI、坏块与可写空间。超过预算停止交付。

原厂 U-Boot 与分区表已补齐。stock/ap8220-stock-uboot.bin 来自用户上传的 8-0-APPSBL.bin，655360 字节，标识为 U-Boot 2016.01（2020-06-28 12:22:09 +0800），内置原始 rootfs1/rootfs2 双槽启动逻辑。原厂布局 MIBIB 与本次上传的 1-0-MIBIB(2).bin 完全一致。

校验确认的是文件结构、大小、版本、启动逻辑与布局的相符性，不等于厂商签名或官方哈希认证。文件来源和完整 SHA256 见 boot-assets/来源与检查记录.json 和 stock/uboot-info.json。当前源码包无需再次运行导入脚本。

发布前仍检查两组启动文件的完整性与哈希，现在该检查已通过。开启 publish 可尝试双布局编译、检查和完整发布；缺件或校验失败时提前停止。取消 publish 只验证编译，不生成可下载的交付。

正式 Release 含两个名称明确的完整发布包，每包包含对应固件、该布局的启动文件、源码、README、来源信息与 SHA256；boot 目录仅放本布局文件，源码 ZIP 保留整个双布局项目。两种镜像及全部启动文件都通过检查后才创建 Release。

从 v1.1.3 自身发起升级时，会检查当前 NAND 布局和镜像 ap8220_layout 元数据；写入前再次检查，普通系统升级不允许跨布局。旧固件不一定具备此保护，首次迁入仍须人工核对。原厂版 active 仅接受 1 或 2，其他值停止升级并要求核对原厂启动环境。

本版针对串口日志中的 new format image overwritten 错误，将 stock 内核加载地址从 0x41000000 调整为 0x44000000；原厂 U-Boot 仍从 0x42000000 读取 FIT，不修改其环境或启动文件。发布检查实际解压普通内核与首刷 initramfs，核验 Image 声明的运行内存、FIT 源数据和实际 DTB 固定保留区互不重叠；FIT 暂存区不得超过 0x44000000，内核结束地址不得超过 0x4A000000。stock 的内嵌 initramfs 使用 XZ 压缩。

这是针对已知内存重叠故障的源码修复；静态检查不等于原厂 U-Boot 实机启动成功。stock 启动与升级仍须首轮设备验收。本版保留此前 RAMFS 命令依赖和 active 读取状态检查，完整验证记录见 docs/源码验证记录.md。

## 出厂 MAC、旧版迁移与主题

v1.1.3 不再使用网卡当前地址或旧版缓存来判断出厂身份。只读 product_info 的 product.mac，遵循上游 WAN=出厂地址、LAN=出厂地址+1（仅低 24 位递增），固定 br-lan 的管理地址。无线 BSSID 保持上游驱动与校准来源，不套用桥接 MAC。

新装、恢复出厂时，无法读取有效出厂地址就停止初始化并记录日志，不以随机地址兜底。正常运行后，状态命令会显示出厂 MAC、管理 MAC 和身份来源。

从本项目旧版保留配置升级时，独立迁移程序在启动配置阶段修正自动生成的设备身份，不受 initialized 标记跳过影响。仅在旧缓存与桥接 MAC 相符时自动迁移；用户已自定义桥接 MAC 时跳过。主机名、DHCP 主机名和 NAS 标识仅在仍为旧自动值时更新，SSID、密码、信道和静态管理地址保留。迁移前配置备份位于 /etc/ap8220-identity-backup，包含无线密码等敏感配置，请勿公开。

管理 MAC 修正后，主路由可能给 AP 分配新的 IP；原有 DHCP 地址保留需改为新管理 MAC。product_info、ART、U-Boot 和 MIBIB 均不会由迁移程序写入。

Footstrap 不是 Bootstrap。本项目从 OpenWrt 官方 LuCI openwrt-25.12 的固定提交接入，来源和模板 SHA256 见 config/footstrap-source.json，并提供 117 条主题简体中文翻译。主仓库与普通软件源仍按每次构建开始时的最新提交冻结。Footstrap 的升级需更新项目内的固定来源并同步翻译检查。

首次安装、恢复出厂默认 Footstrap；Argon 保留，可在“系统 → 系统 → 语言和界面”切换。保留配置升级不强制更换当前主题。系统、Turboacc、usteer 中文包继续保留，并增加 luci-i18n-footstrap-zh-cn。

## 版本号

源码版本以 VERSION 为唯一输入，目前为 1.1.3。固件版本由源码版本、北京时间日期、运行编号和重跑次数组成，例如：

    源码版本：v1.1.3
    固件版本：v1.1.3-R26.10.23-b1.1
    发布标签：AP8220-AP-v1.1.3-R26.10.23-b1.1

固件内部、LuCI 系统描述、SSH 登录横幅、状态命令和交付文件名使用同一固件版本。

主仓库采用构建开始时解析到的最新提交；软件源保留 Lean 指定的分支，逐一冻结提交。usteer 单独采用 OpenWrt 官方 packages 中的维护配方。每次交付附源码版本锁，记录这些输入以及本项目提交。时间戳和密码盐会随构建变化。

修改源码时递增 VERSION，并同步 README 和 CHANGELOG 的版本记录。

## 编译时指定出厂参数

打开 Actions 的 Run workflow，在表单中填写；不必为每次参数调整修改仓库文件。

| 表单参数 | 用途与默认值 |
| --- | --- |
| wifi_ssid | 2.4GHz SSID，默认 Home-WiFi |
| wifi_ssid_5g | 5GHz SSID，留空与本次 2.4GHz 一致；需要分频名称时单独填写 |
| wifi_key | 两个频段的 Wi-Fi 密码，默认 12345678 |
| root_password | LuCI 与 SSH 共用的 root 管理密码，默认 password |
| channel_2g | 默认 1；第二台可填写 11；支持 auto |
| channel_5g | 默认 36；第二台可按法规及现场环境填写 149；支持 auto |
| mobility_domain | 四位十六进制移动域，默认 a1b2；两个频段共用，两台 AP 保持一致 |
| country | 两位国家码，默认 CN，按实际使用地区填写 |

密码的取值顺序为：表单非空输入 → 同名仓库 Secret（WIFI_KEY、ROOT_PASSWORD）→ config/ap-defaults.json 的基础值。表单不是秘密输入框；不希望密码进入工作流事件参数时，在仓库 Settings → Secrets and variables → Actions 创建这两个 Secrets，并把表单中的两个密码留空。日志会注册密码掩码。

本次完整参数仅在 work/ap-profile.json 中临时生成，权限为 0600。发布说明、构建信息和源码压缩包中的“本次出厂参数（不含密码）.json”只记录非密码参数。源码的 config/ap-defaults.json 保留通用基础值，不能当成本次构建的最终参数。复现构建时重新提供密码。

固件本身必须包含无线密码和 root 密码哈希，下载固件的人可以提取；Secrets 不会使公开发布的固件具备密码保密能力。

主机名前缀、带宽和 11r 开关等进阶选项仍可修改 config/ap-defaults.json。手动构建时先用环境变量运行 scripts/configure_profile.py，再给 prepare.py 和 collect.py 传入同一个 --profile 文件。

无线密码须为 8—63 个 ASCII 字符。SSID 按 UTF-8 限制为 32 字节。为保证 UCI 配置明确可解析，SSID 和无线密码不接受单引号、反斜杠或控制字符。

默认两个频段统一为 Home-WiFi，移动域为 a1b2。两台 AP 的对应 SSID、密码和移动域应一致，AP 身份按 MAC 自动区分。也可将 wifi_ssid、wifi_ssid_5g 分别设为 RMWIFI、RMWIFI_5G。

编译参数决定首次安装和恢复出厂的配置。本项目后续保留配置升级仍保留设备现有设置；仅重新编译不会覆盖已有 SSID 或管理密码。

## 文件用途与首次安装

详细步骤见 docs/首次安装与升级.md。

- factory.ubi：完成匹配的 U-Boot 与 MIBIB 分区准备后，供支持 NAND Factory UBI 的 Web U-Boot 首次刷入。
- sysupgrade.bin：本项目同分区布局的后续系统升级。
- 源码.zip：本次项目构建源码、上游版本锁及完整编译配置。上游 Lean、软件源和 usteer 按锁文件下载。
- sha256sums：对最终发布的文件重新生成的 SHA256 校验。

本项目随各自发布包提供经核验的 U-Boot 与 MIBIB，正常 sysupgrade 不刷写它们，不修改原厂 ART 校准数据。首次从其他固件迁入请勿保留配置；后续本项目保留配置升级会保留原有网络、无线和密码设置。

## 两台 AP 的使用

每台 AP 使用一个有线口连接主路由 LAN 或交换机，另一个口可以接电脑或下游设备。电脑和无线终端都从主路由获取地址。

在主路由 DHCP 客户端列表中查找 AP8220- 加 MAC 后六位的主机名。需要稳定管理地址时，在主路由为两台 AP 分别做 DHCP 地址保留。

需要不同出厂信道时，可分别编译：第一台使用 1 / 36，第二台按环境使用 11 / 149。也可以刷同一个固件后在第二台 LuCI 中修改信道。自动选信道不能保证两台一定选到不同信道。

usteer 通过 lan 网络交换信息，默认共享邻居信息并使用温和策略，不主动启用弱信号或负载强制踢人，不默认启用定时跨频段引导。漫游仍由终端决定，11r 可在 LuCI 中关闭以适应旧设备。

Turboacc 页面保留，默认使用 NSS ECM。页面状态与实际无线桥接加速效果分别验收，不叠加 SFE 或另一套 Flow Offloading。

## 检查与验收

- 源码检查：版本、默认参数、包选择、工作流固定提交、Shell 语法与 ShellCheck。
- 初始化测试：构建固定版本的真实 OpenWrt UCI，在隔离目录执行初始化脚本，验证双口桥接、DHCP、无线反向编号、设备身份、延迟初始化和升级保护。
- 编译配置检查：make defconfig 后核验必装包、禁用包、唯一 AP8220 目标与 NSS/Turboacc 选项。
- 实际交付检查：FIT/DTB 内的设备、各自 NAND 布局与原厂 ART 定义，UBI 格式与 CRC，Factory 和 Sysupgrade 组件一致性，实际软件包清单、固件内部版本、编译参数及管理密码哈希。软件包按本次 Lean 的 ABI 元数据解析实际名称。

## 从 v1.0.0 修复交付检查故障

如果编译步骤已成功，随后提示缺少 libustream-openssl，这是旧版检查器未处理 libustream-openssl20201210 等 ABI 包名所致。v1.1.3 根据 staging_dir 中本次构建生成的 pkginfo/*.version 核验，仍会拒绝真正缺包、错误 ABI 和禁用的 TLS 后端。

用新包中的内容覆盖仓库根目录，包含 .github、scripts、tests、config、package、VERSION 和文档。提交后在新提交上点击 Run workflow 新建一次构建。直接 Re-run 旧失败任务仍会使用旧提交中的检查脚本。

CI 不模拟 IPQ8071A 硬件，也不执行实机刷入。首轮设备验收见 docs/实机验收清单.md。

如需手动查看设备信息，在 SSH 中运行：

    ap8220-ap-status
    logread -e ap8220-ap

## 源码组织

| 路径 | 作用 |
| --- | --- |
| VERSION | 源码版本 |
| config/ap-defaults.json | 出厂基础参数；编译表单可覆盖 |
| config/ap8220-ap.config | AP 编译选项 |
| config/package-policy.json | 必装、禁止包与关键选项 |
| package/ap8220-ap-defaults | 首次启动、中文版本信息和状态命令 |
| scripts | 上游锁定、准备、检查、编译与交付程序 |
| tests | 配置、初始化与镜像检查测试 |
| .github/workflows | 简体中文检查和编译发布工作流 |
| docs | 首次安装、升级、设计和实机验收说明 |

项目脚本采用 GPL-2.0-only。Lean、OpenWrt、LuCI、Argon 及其他上游组件保留各自许可证和版权。


# 固件刷写教程

## 选择资料与固件

| 目录 / 标记 | 目标布局 | 启动端要求 | 已附文件 |
| --- | --- | --- | --- |
| stock | rootfs1 48MiB、rootfs2 48MiB、usrdata 剩余 32MiB | 保留原厂 U-Boot 和对应启动环境 | 原厂布局 MIBIB、原厂方案 U-Boot（来源与版本已记录） |
| large128 | rootfs 使用整片 128MiB NAND | 本教程采用 chenxin527 AP8220 Web U-Boot | 第三方 U-Boot、128MiB MIBIB |

随包提供启动文件，是为了首次转换布局和后续恢复。同布局的正常固件升级只使用对应的 sysupgrade.bin，无须每次重刷 U-Boot 或 MIBIB。

配套启动资料不包含 APPSBLENV、ART、CDT、完整 SPI 镜像。这些分区的本机备份应另外妥善保存；尤其不要用其他设备的 ART、产品信息或环境变量覆盖本机数据。

## 刷写前的检查与备份

1. 确认设备为上述原版硬件，非改内存、改闪存版本。
2. 将电脑、AP 直连，准备可靠电源。需要 Console 时使用设备外露 Console 接口及兼容的线材，串口设为 115200、8N1、无流控。
3. 备份本机 U-Boot、MIBIB、APPSBLENV、ART，保存当前分区表和启动信息。先复制到电脑并验证文件大小和 SHA256，再开始写入操作。
4. 核对配套启动资料 sha256sums，以及各目录 sha256sums。Windows 可用 Get-FileHash，Linux 可用 sha256sum -c sha256sums。
5. 根据本机实际布局选择 stock 或 large128。普通系统升级不承担两种分区布局之间的转换。

Linux / OpenWrt 只读检查：

```sh
ubus call system board
cat /proc/mtd
cat /proc/cmdline
fw_printenv active bootcmd bootlinux boot3 boot4 setup1 setup2
```

没有 fw_printenv 时跳过该命令；不要为读取环境变量而写入猜测的 fw_env.config。

在有 SSH 的系统中，按分区名称导出 U-Boot 与 MIBIB。下面命令只读取设备，向 /tmp 新建备份：

```sh
backup_dir="/tmp/ap8220-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
cat /proc/mtd > "$backup_dir/proc-mtd.txt"
cat /proc/cmdline > "$backup_dir/cmdline.txt"

boot_mtd="$(awk 'tolower($4)=="\"0:appsbl\"" {sub(/:$/, "", $1); name=$1; count++} END {if (count==1) print name}' /proc/mtd)"
mibib_mtd="$(awk 'tolower($4)=="\"0:mibib\"" {sub(/:$/, "", $1); name=$1; count++} END {if (count==1) print name}' /proc/mtd)"
if [ -n "$boot_mtd" ] && [ -n "$mibib_mtd" ]; then
    dd if="/dev/$boot_mtd" of="$backup_dir/APPSBL.bin" bs=65536
    dd if="/dev/$mibib_mtd" of="$backup_dir/MIBIB.bin" bs=65536
    wc -c "$backup_dir/APPSBL.bin" "$backup_dir/MIBIB.bin"
    sha256sum "$backup_dir/APPSBL.bin" "$backup_dir/MIBIB.bin"
else
    echo '未唯一识别到启动分区，请停止并核对 /proc/mtd。'
fi
```

预期大小：APPSBL 655360 字节，MIBIB 65536 字节。若名称重复或识别结果不止一行，先停止并核对，不执行读取。其余分区按 /proc/mtd 中本机实际名称备份；本机环境备份不要公开发布。

已换成第三方 U-Boot 的机器，现在导出的 APPSBL 也是第三方版本，不能将其改名作为原厂 U-Boot。原厂文件应从仍保留原厂引导程序的 AP8220 导出。

## 原厂布局固件的首次安装

前提：本机仍是原厂布局、原厂 U-Boot；该次发布包已提供经过检查的 stock-initramfs-uImage.itb 与 stock-sysupgrade.bin。

保留现有 U-Boot、MIBIB，不刷配套启动资料的分区表。安装路线参考 OpenWrt 官方 AP8220 支持提交中的内存启动方法：

1. 准备 stock 的 initramfs 镜像，复制一份命名为 initramfs.bin，放入电脑 TFTP 根目录。
2. 隔离其他网络，电脑静态 IPv4 设为 192.168.1.2/24。接 Console，设备通电后连续按 @ 中断原厂 U-Boot。
3. 逐行执行；下载失败立即停止，不继续 bootm：

```text
setenv ipaddr 192.168.1.1
setenv serverip 192.168.1.2
tftpboot 0x42000000 initramfs.bin
bootm 0x42000000
```

这里只在内存中设置 TFTP 参数，没有 saveenv；没有写入 U-Boot、MIBIB 或 NAND。v1.1.3 的 stock 镜像必须在日志中显示 Load Address 为 0x44000000，暂存地址保持 0x42000000；旧版地址不适用于此检查。启动后确认布局是 rootfs1、rootfs2、usrdata。若设备当前启动环境已被手动改为其他加载地址，需要先核对该环境。

4. RAM 系统运行后，将 AP 另一个网口连接主路由 LAN，电脑恢复 DHCP。AP 专用配置也从上级 DHCP 获取管理地址，在主路由租约列表查找 AP8220 主机名。
5. 进入该 RAM 系统的 LuCI，上传配套 stock-sysupgrade.bin，首次安装取消保留配置。或将文件上传至 /tmp 后运行：

```sh
sysupgrade -n /tmp/stock-sysupgrade.bin
```

文件路径按实际上传名称修改。必须是明确支持原厂分区选择的 stock 版本。不要将旧版 v1.0.1 的 large128 镜像用于这一步。

6. 重启后重新查找 DHCP 管理地址，核验两个有线口桥接、无线、密码和分区。保留的另一系统槽不等于本项目已经实现自动回滚。

参考：[OpenWrt 官方 AP8220 支持提交](https://lists.infradead.org/pipermail/lede-commits/2025-February/024422.html)。

## 转换为 128MiB 大分区并首次安装

本节采用配套启动资料固定版本的 chenxin527 Web U-Boot。开始前完成本机备份，确认 Console 能正常中断启动。

### 1. 已经是匹配的 Web U-Boot 与大分区

跳过 U-Boot、MIBIB 的写入，直接进入本节第 4 步。在 Web 或系统分区信息中确认 NAND 为约 128MiB 的单 rootfs。

### 2. 从原厂 U-Boot 安装第三方 U-Boot

仅适用于分区地址与配套启动资料检查记录一致的原版 AP8220。把 large128 目录下的第三方 U-Boot 文件复制一份命名为 uboot.bin，放入电脑 TFTP 目录。

电脑保持 192.168.1.2/24，进入原厂 U-Boot 后逐行执行：

```text
setenv ipaddr 192.168.1.1
setenv serverip 192.168.1.2
tftpboot uboot.bin
```

核对下载文件为 655360 字节，且电脑侧 SHA256 与配套记录一致。然后才执行：

```text
flash 0:APPSBL
```

确认写入成功，保持电源稳定；随后按住 Reset 重启进入新 Web U-Boot。本教程不默认擦除 APPSBLENV，不套用其他教程的整片 SPI 擦除命令。

### 3. 在 Web U-Boot 中更新为 128MiB 分区表

1. 按住 Reset 给设备通电，LED 闪烁三次后常亮再松开，访问 http://192.168.1.1 。此地址属于 U-Boot，不是 AP 固件固定管理地址。
2. 打开分区表更新页面，选择配套启动资料 large128/ap8220-large128-mibib.bin；确认操作目标是 MIBIB。若当前版本没有对应入口，先停止并核对该 U-Boot 文档，不把 MIBIB 当固件上传。
3. 更新成功后重新进入 Web U-Boot，核对分区已重载为单个 rootfs，覆盖 128MiB NAND。

从两个 48MiB 系统槽合并到单 rootfs 后，原 NAND 系统和数据不再按旧布局使用；后续需要重新刷入大分区固件。

### 4. 首次刷入大分区固件

1. 在 Web U-Boot 固件更新页面，上传对应发布版的 large128-factory.ubi。
2. 核对设备与 NAND 分区信息后执行写入。完成前不要断电。
3. 重启进入固件，把 AP 接到主路由 LAN，电脑恢复 DHCP；在主路由租约表查找 AP8220 主机名和管理 IP。
4. 默认参数以该次固件发布说明为准。当前源码 v1.1.3 的基础值为双频 Home-WiFi、无线密码 12345678、root 密码 password；编译时可覆盖。

该版本 Web U-Boot 支持 NAND Factory UBI，作者明确列出 NAND Sysupgrade 尚不支持，因此在这个页面使用 factory.ubi。不要将其他格式简单改扩展名后上传。

参考：[chenxin527 使用说明](https://github.com/chenxin527/uboot-qsdk12.5-build/blob/main/README.md)、[固定发布版本](https://github.com/chenxin527/uboot-qsdk12.5-build/releases/tag/26.08.16-14.22.36-3011049)。

## 同布局的后续固件升级

1. 备份 LuCI 配置，核对当前布局与待刷固件的 stock / large128 标记一致。
2. 在已经启动的 OpenWrt / LEDE 内，通过 LuCI 上传对应 sysupgrade.bin。
3. 首次从其他发行版迁入不保留配置。本项目后续同布局升级可保留配置；这时新的编译 SSID 和密码不会覆盖设备现有设置。
4. 升级完成后重新确认管理地址和无线状态。无需重刷 U-Boot 或 MIBIB。

## 大分区恢复原厂布局

stock 目录现已包含原厂方案 U-Boot、原厂布局 MIBIB 和来源信息。实际固件发布包的文件以 boot 目录与发布包信息.json 为准；这些文件不包含本机原来的 APPSBLENV。

恢复需要原厂 U-Boot、原厂布局 MIBIB、适配 stock 的固件，以及本机原来的启动环境或经核对的启动参数。仅恢复 MIBIB 不会恢复原厂系统内容；仅刷 stock 固件也不会转换启动端分区表。

跨布局恢复还需要核对本机原来的 APPSBLENV 与启动参数，因此不提供未经本机核对的通用恢复写入命令。若机器已经是第三方 U-Boot，请先保留其可进入的 Web / Console 恢复入口。

## 发布打包清单

| 发布版 | 固件与说明 | 启动文件 |
| --- | --- | --- |
| stock | stock-initramfs-uImage.itb、stock-factory.ubi、stock-sysupgrade.bin、README.md、构建版本与校验 | 原厂布局 MIBIB、已附原厂方案 U-Boot 与来源记录 |
| large128 | large128-factory.ubi、large128-sysupgrade.bin、README.md、构建版本与校验 | 固定版本 chenxin527 U-Boot、128MiB MIBIB |

每个发布包各自记录源码版本、固件版本、U-Boot 版本或备份来源、MIBIB SHA256 和全部文件 SHA256。启动文件完整性检查已通过；本次源码修改尚未经过整机交叉编译和硬件刷入验证。

U-Boot 与 MIBIB 不由首次启动脚本或正常 sysupgrade 自动刷写；用户按本 README 的对应场景单独操作。
