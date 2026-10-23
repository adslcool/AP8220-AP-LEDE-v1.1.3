# AP8220 AP 专用默认配置，GPL-2.0-only。
include $(TOPDIR)/rules.mk

PKG_NAME:=ap8220-ap-defaults
PKG_VERSION:=@SOURCE_VERSION@
PKG_RELEASE:=1
PKG_LICENSE:=GPL-2.0-only

include $(INCLUDE_DIR)/package.mk

define Package/ap8220-ap-defaults
  SECTION:=utils
  CATEGORY:=Utilities
  TITLE:=AP8220 AP 专用默认配置与中文状态信息
  DEPENDS:=+uci +ubus +jsonfilter +fwtool +uboot-envtools +wpad-openssl +usteer +luci-theme-argon +luci-theme-footstrap +luci-i18n-footstrap-zh-cn +luci-app-turboacc
endef

define Package/ap8220-ap-defaults/conffiles
/etc/config/ap8220_ap
endef

define Build/Compile
endef

define Package/ap8220-ap-defaults/install
	$(CP) ./files/* $(1)/
endef

$(eval $(call BuildPackage,ap8220-ap-defaults))
