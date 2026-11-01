# Rooted Android 部署

这套脚本在已有的 ARM64 Linux chroot 中运行 Store、Caddy、维护 SSH 和可选 DDNS。它不是一键安装器，需要部署者准备 root 权限、Magisk、兼容的 Linux rootfs 以及网络入口。

## 环境与目录

Linux 环境需要 Python 3.12、Java、F-Droid 工具、aapt、apksigner、Caddy、runit、OpenSSH、util-linux 和 curl。Caddy 的 IPv4 转发示例另外依赖 Cloudflare DNS 和动态上游模块。

脚本默认使用下列固定安装布局；部署到其他位置时需统一调整相关脚本：

```text
/data/adb/ming-store/
  control.sh, services.sh, guardian.sh, enter.sh
  rootfs/
    app/                    源码与依赖
    data/                   当前仓库、签名材料
    config/                 runtime.json、Caddyfile、maintenance-sshd.conf、ddns.json
    run/secrets/            API Key、可选 DNS Token
    logs/                   滚动日志
    caddy/                  证书与 ACME 状态
    services/               runit 服务与停止标记
/data/adb/ming-sshd/          维护 SSH 的密钥与登录入口
/data/adb/service.d/90-ming-store.sh
```

这是安装布局，不包含部署者的地址或凭据。rootfs、密钥、证书和运行数据不随源码提供。将安装目录设为 root 私有，为上传、下载和 HTTPS 工作进程预留专用 UID 6001、6002、6003，不要与现有应用身份混用。

## 私有配置

将示例复制到 chroot 内的 `/config/`，只编辑副本：

| 源码示例 | 私有目标 | 需配置的内容 |
| --- | --- | --- |
| `deploy/android/runtime.example.json` | `/config/runtime.json` | 上传绑定地址、仓库下载 URL |
| `deploy/android/Caddyfile.example` | `/config/Caddyfile` | 自有域名、TLS 与公开下载入口 |
| `deploy/android/maintenance-sshd.example.conf` | `/config/maintenance-sshd.conf` | 受信任接口、SSH 主机密钥和授权 |
| `deploy/android/ddns.example.json` | `/config/ddns.json` | 自有 DNS zone、记录、网卡、令牌文件位置 |

默认上传和维护 SSH 仅绑定回环地址。需要远程维护时，先将 SSH 的 `ListenAddress` 改成设备实际内网接口，再用 `sshd -t` 校验；保留可用的 ADB 恢复通道。示例里的 `example.invalid` 与全零 zone ID 必须替换。

`install_services.py` 保留已有 `/config/maintenance-sshd.conf`；缺少配置时只复制回环监听的示例。初始化维护目录时，它可从现有 Termux 环境复制授权公钥与主机密钥，因此首次部署必须先准备这些文件，或在维护目录安装自己的密钥。脚本会修改 chroot 的 root 登录 shell，但不会启动服务。

API Key 使用 `/run/secrets/store_api_key`，仅让 API 工作进程读取；下载进程不持有 Key。DNS Token 使用配置指定的文件，保持 root 所有且权限 0600。将 Token 权限限定到实际需要的 DNS zone，应用里的记录白名单不能代替服务商权限控制。

## 运行与维护

`enter.sh` 创建私有挂载命名空间进入 chroot。runit 分别管理 `store`、`sshd`、`health`、`ddns`，新服务安装后默认停止。准备好配置并验证后，再通过 Android root shell 启动所需服务：

```sh
/data/adb/ming-store/services.sh store start
/data/adb/ming-store/services.sh sshd start
/data/adb/ming-store/services.sh health start
/data/adb/ming-store/control.sh status
```

`stop` 保留停止标记，重启后仍保持停止；健康检查尊重该标记并对故障重启退避。商店和 SSH 各自持有唤醒锁，需要评估设备耗电、网络休眠和系统后台策略。

业务代码更新只同步 `store/` 和所需脚本，避免覆盖 `/data`、`/config`、`/run/secrets`、证书及 SSH 身份。修改 SSH 或服务定义后先校验，再单独重启对应服务。删除 rootfs 前必须另行安排维护入口。

## 可选双栈入口

手机可维护自己的 AAAA 记录并通过 Caddy 提供 IPv6 HTTPS。独立 IPv4 代理参考 `deploy/android/Caddyfile.ipv4.example`：上游只解析 AAAA、校验 TLS 域名，避免固定 A 指向代理自身后形成回环。公开入口仅转发 GET/HEAD 下载和健康检查。

DDNS 只修改配置中具有匹配管理标记的 AAAA，保留其他 A 记录；缺少记录时需显式执行 `update_dns.py --initialize`。验证域名和 Token 权限后再启动 `ddns`。DNS、证书、网络可达性和设备重启恢复需在实际环境验证，CI 不访问真实设备。

## 客户端源码下载

发布 Ming Store APK 时，将对应完整源码按最终 APK SHA-256 命名，长期保存在
`/data/client-sources/<apk-sha256>.tar.gz`，权限 0644，目录权限 0755。按哈希命名的文件
保持不可变；相同路径已存在时先核对哈希，不覆盖不同内容。此目录独立于仓库 generation，
普通 APK 发布和旧 generation 清理不会删除源码。

将 `client-downloads.example.caddy` 复制到私有 `/config/client-downloads.caddy`，
在现有 Caddy 的下载站点内添加 `import /config/client-downloads.caddy`。先校验配置，
再按所用 Caddy 版本支持的方式加载配置，保留现有 TLS、DNS 和签名身份。

- 永久地址：`/fdroid/repo/client-sources/<apk-sha256>.tar.gz`。
- 当前版本：`/fdroid/repo/client-source.tar.gz`，读取目录中的 `current.tar.gz` 相对符号链接。
- 根路径别名 `/client-sources/...`、`/client-source.tar.gz` 供直接连接下载站点的旧链接使用。

仓库前缀可复用现有 IPv4 转发规则。私有 `.env.client` 的 `STORE_CLIENT_SOURCE_URL`
应指向自身域名的 `/fdroid/repo/client-source.tar.gz`，无需在每次升级时修改客户端源码链接。
源码文件先完整写入隐藏临时文件、校验并原子改名；`current.tar.gz` 也通过临时链接加
原子替换更新。公开发布 APK 前，检查永久源码地址可用，GET/HEAD/Range 与本地源码哈希一致。
