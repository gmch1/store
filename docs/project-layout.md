# 项目归属、公开源码与私有配置

本仓库同时维护我们自己的 Store 服务端，以及基于 Droid-ify 的 Ming Store 客户端定制。
两部分独立构建；实际部署配置和签名身份单独保管。

| 部分 | 归属与许可证 | Git 中保存什么 |
| --- | --- | --- |
| `store/`、上传和部署脚本 | 我们的服务端，MIT | 业务代码和通用脚本，可公开 |
| `deploy/android/*.example*`、`.env.example` | 我们的部署示例，MIT | 占位地址和通用参数，可公开 |
| `client/upstream.json` | Droid-ify 上游的精确来源，GPL-3.0-or-later | 固定提交和来源信息，可公开 |
| `client/patches/`、`client/LICENSE` | 我们对上游的 Android 衍生修改，GPL-3.0-or-later | 通用定制、更新修复和合成测试，可公开 |
| `client/release.json` | 我们的发布身份和版本 | 包名、versionName、versionCode，可公开 |
| `scripts/client_config.py`、`prepare_client.py`、`build_client.py` | 我们的构建工具，MIT | 配置规则、准备、测试、签名和源码归档逻辑，可公开 |
| `.env.client.example` | 我们的客户端配置示例 | 合成仓库和全零指纹，可公开 |
| `.env.client`、`*.local.env/json/patch` | 实际部署参数与本地覆盖 | 私有，被 Git 忽略 |
| `~/.local/share/ming-store/signing/` 或自定义签名目录 | 已有 APK 签名身份 | 私钥、密码均不进入 Git |
| `.local/` | 本地构建与运行数据 | 上游克隆、APK、源码归档、测试仓库、设备报告和截图，被 Git 忽略 |

“我们的代码”与“能够公开”是两个不同维度：服务端和构建工具可按 MIT 公开，客户端
衍生修改按 GPL 公开。Droid-ify 本身仍归上游作者；这里固定来源并保留署名，不重新标作自有代码。
公开的源码归档随 APK 单独交付，其中需要包含上游源码与全部修改。

## 配置只走一条入口

客户端统一从 `.env.client` 或同名环境变量读取配置，使用
`python3 scripts/build_client.py` 构建。程序只把仓库地址、仓库证书指纹和源码地址生成到
准备目录中的 `StoreConfig.kt`；密钥路径、密码文件和环境变量全集不进入 Android 源码或归档。
详细字段见 [客户端说明](../client/README.md)。

服务端继续使用 `.env`、`deploy/android/` 的实际私有配置以及部署目录中的 secrets。
客户端不复用服务端 `.env`。上传 API Key、DNS Token、SSH/TLS 身份只属于部署环境，
不通过 APK 或公开 Git 分发。

`.gitignore` 防止常规误加入；`scripts/check_public_files.py` 还会拒绝强制加入的
实际 dotenv、本地覆盖、密钥、运行数据库和未知部署地址，并验证客户端示例仍为占位配置。
CI 仅使用 `--example-config --unsigned`，不需要实际域名、签名文件或开发机连接。

## 日常维护

1. 修改服务端时直接编辑 `store/`；修改客户端时在 `prepare_client.py` 生成的独立目录中编辑。
2. 新客户端改动可导出该目录的未暂存 diff 为新补丁，加入 `client/patches/series.json`。
   新文件先用 `git add -N` 纳入 diff。生成的连接配置已经暂存在准备目录，正常导出未暂存改动时不会混入本地部署值。
3. 更换上游只调整 `client/upstream.json` 的精确版本并检查补丁兼容；不要把整个构建目录复制进源码仓库。
4. 发布版本只调整 `client/release.json`，执行统一构建命令，再检查公开文件和相关测试后推送。
5. APK 和完整源码发布到应用仓库属于独立发布步骤；Git 推送不重启或部署 Store。

实际配置已存在时直接复用，签名文件保持原位置。之前包含部署历史的旧工作区不能用于
公开推送；新分支继续从公开 `main` 创建，只推指定分支，不使用 `--all` 或 `--mirror`。
