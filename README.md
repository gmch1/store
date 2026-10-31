# Store

自托管的 Android 应用分发服务。通过内网 API 接收已签名 APK，校验包名、签名和版本，生成带签名的 F-Droid 仓库，供 Droid-ify 等客户端同步与更新。

[源码](https://github.com/gmch1/store) · [CI](https://github.com/gmch1/store/actions/workflows/ci.yml) · [MIT License](LICENSE)

## 功能

- 首次上传自动创建应用，读取名称、版本与图标；相同 APK 重复上传返回 `unchanged`。
- 同一包名必须保持签名一致并递增 versionCode，每个包名只保留最新版本。
- 先构建和核对新索引，再原子切换当前仓库；失败时保留原仓库。
- 下载支持 Range，更新前已经打开的下载可继续完成。
- 上传 API 与公开下载入口分离，下载进程只读数据且不持有上传凭据。
- 支持 Linux 主机的 Docker Compose 部署；另提供 rooted Android 的进程监护、维护 SSH 和可选 DDNS 脚本。

服务不提供账号系统、审核、评论、历史版本归档或静默安装。应用构建和 APK 签名由各项目完成。

## 快速开始

需要 Docker 和 Docker Compose，在仓库目录执行：

```bash
bash scripts/setup-service.sh
# 按 .env.example 编辑本地 .env
docker compose up -d --build
```

上传 API 默认监听 `127.0.0.1:8767`，下载服务默认监听 `127.0.0.1:8766`。API Key 自动写入 `.local/api-key`，仓库数据和签名材料存放在 `.local/data/`。这些文件不纳入版本控制。

本地上传示例：

```bash
python3 scripts/upload.py /path/to/app-release.apk \
  --url http://127.0.0.1:8767 \
  --key-file .local/api-key \
  --notes-file /path/to/changelog.txt
```

服务在签名索引生效后才返回成功。手机同步仓库后发现更新，安装由客户端与系统处理。对外使用时，为下载服务配置 HTTPS，将 `STORE_REPO_URL` 改成自己的仓库地址。上传 API 只绑定受信任的本机或内网接口，不经过公开下载代理。

## 文档

- [部署、API 与数据管理](docs/service.md)
- [Rooted Android 部署](docs/android-deployment.md)
- [安全边界与公开范围](SECURITY.md)
- [早期方案调研](docs/open-source-options.md)

## 测试与 CI

测试使用临时仓库、现场生成的测试签名和独立测试 APK，不需要生产 API Key、DNS Token、手机连接或部署数据。

需要 Python 3.12、Java 17、`libmagic`、Android SDK build-tools 35.0.0 和 platform android-35（或 android-36）。设置 `ANDROID_HOME` 后：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q tests
```

GitHub Actions 在推送 `main`、向 `main` 提交 PR 和手动运行时触发，执行全部测试、公开文件检查、Compose 配置校验与容器构建。CI 不部署服务、不向正式仓库上传应用。

## 许可证

本仓库自有代码采用 [MIT](LICENSE)。第三方依赖保持其各自许可证；`fdroidserver` 通过独立命令调用，其发行包声明 AGPL v3 或更新版本。本仓库不分发 APK、Droid-ify 客户端、Linux rootfs 或第三方二进制工具。分发包含这些依赖的镜像时，还需遵循相应依赖的许可证。
