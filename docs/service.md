# 精简发布服务

服务通过内网 API 接收已经签名的完整 APK，自动创建应用、生成 F-Droid 索引，每个包名仅保留最新版。没有审核、上架、账号、数据库或任务队列。构建和应用签名留在各项目。

## 运行

下面使用普通 Linux 主机和 Docker Compose 部署。Rooted Android 的运行方式见 [Android 部署](android-deployment.md)。所有地址均由部署者配置。

```bash
bash scripts/setup-service.sh
# 按 .env.example 调整 .env
docker compose up -d --build
docker compose ps
docker compose logs --tail=80 api downloads
```

一个镜像运行两个容器。`api` 提供上传；`downloads` 仅提供下载，数据卷只读，不挂载 API Key。首次启动自动生成仓库密钥，重启沿用当前数据。修改 `STORE_REPO_URL` 后重新创建 API 容器，会为现有 APK 重新生成索引。

API Key 自动生成在 `.local/api-key`，权限 0600，不打印到终端。它可发布所有应用；CI 应以凭据文件提供，不写入源代码。更换 Key 后重启 API 容器。

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| STORE_API_BIND / PORT | 127.0.0.1 / 8767 | 上传监听地址与端口 |
| STORE_DOWNLOAD_BIND / PORT | 127.0.0.1 / 8766 | 下载监听地址与端口 |
| STORE_REPO_URL | http://127.0.0.1:8766/fdroid/repo | 写入签名索引的客户端下载地址 |
| STORE_MAX_APK_BYTES | 536870912 | 单 APK 上限 512 MiB |
| STORE_UID / GID | 1000 / 1000 | 容器用户；数据目录需归该用户所有 |

允许其他内网服务上传时，把 API 绑定到本机的内网 IPv4 地址。API 额外检查 TCP 来源属于回环、RFC1918 私网或 ULA，不信任 X-Forwarded-For。现有 IPv6 HTTPS 入口只转发下载服务，不转发上传端口。

将 `STORE_REPO_URL` 设置为自己的 HTTPS 仓库地址。入口只转发下载服务，TLS 证书和 DNS 凭据放在部署环境；`.env.example` 默认仅使用本地回环地址。

## API 与项目接入

除 `/healthz` 外均需要 `X-API-Key` 请求头。

| 方法与路径 | 行为 |
| --- | --- |
| GET /healthz | 检查当前仓库可读 |
| GET /api/v1/apps | 仓库 URL、指纹和各应用当前版本 |
| GET /api/v1/apps/{package} | 查询单个应用当前版本 |
| POST /api/v1/releases | 上传 APK，自动创建应用或升级 |

上传 Content-Type 使用 `application/vnd.android.package-archive` 或 `application/octet-stream`。请求体是 APK 原始字节，**不是 multipart/form-data**。可通过 URL 编码的 `notes` 参数提供更新说明，最多 8192 字节。不要在说明中写凭据，访问日志可能记录 URL。

推荐使用自带的 Python 标准库客户端，无需安装依赖：

```bash
STORE_API_URL=http://127.0.0.1:8767 \
STORE_API_KEY_FILE=/path/to/store-api-key \
python3 scripts/upload.py /path/to/app-release.apk \
  --notes-file /path/to/changelog.txt
```

这一步可放在各项目构建、签名之后，由 Skill、本机代理或内网 CI runner 调用。公网托管 runner 不会天然具备内网访问能力。客户端在网络错误、503 等临时故障时最多尝试四次。

发布完成返回 201，相同 APK 返回 200。返回体包含 `status`（`published` 或 `unchanged`）、`app`（包名、名称、version_code、version_name、sha256、文件名等）和 `repo_url`。

**200/201 在签名索引生成并生效后才返回。** 如果未收到响应，可以重试同一个 APK。`unchanged` 不修改该版本更新说明。手机仍需同步仓库才能发现更新。

401 表示 Key 错误；403 来源非内网；409 签名或版本冲突；413 包过大；415 内容类型错误；422 无效 APK 或说明；503 已有发布进行中，带 Retry-After；500 索引生成失败，可查看容器日志。

新版本必须签名一致、versionCode 递增。同版本不同文件和旧版本会被拒绝。当前不实现签名轮换，也不支持拆分 APK 或同包名多 ABI 并列版本；请上传一个完整独立 APK。

## 数据和发布一致性

```text
.local/api-key                 API 凭据
.local/data/signing/           仓库私钥及受限配置
.local/data/incoming/          上传暂存，完成或失败后删除
.local/data/generations/<id>/  repo/、metadata/、state.json
.local/data/current            指向当前 generation 的符号链接
```

一次发布的顺序：限量流式接收 → 签名/版本校验 → 使用硬链接构建新仓库 → 生成并签名索引 → 核对版本和哈希 → 原子替换 current → 删除旧目录。

上传最长 300 秒，索引生成最长 600 秒。同一时间只允许一次发布，其他上传返回 503；下载不会等待索引生成。失败时 current 不变。进程中断的临时数据在下次 API 启动时清理。

稳定状态每个应用只保留一份 APK。发布期间，新包和被替换的旧包短暂并存；未变更 APK 使用硬链接，不复制额外磁盘数据。下载先打开文件，即使随后删除旧目录，已开始的下载仍能完成；旧包磁盘块在最后一个下载结束后释放。旧版本的新下载请求返回 404，客户端需重新同步。

服务只清理自身数据目录，不删除其他项目的构建产物。至少备份仓库 `signing/`、当前 generation 和 API Key；服务不会自动制作历史 APK 备份。

## 导入已有仓库密钥

仅在新服务尚未初始化时执行：

```bash
docker compose run --rm \
  -v "$PWD/.local/fdroid:/import:ro,z" \
  api init --import-repo /import
```

只导入密钥，不复制历史 APK。启动后通过 API 导入需要的当前 APK。确认原仓库指纹和客户端同步成功后，可清理旧 `.local/fdroid/repo/` 的冗余包。不要再使用旧手工仓库发布；`scripts/publish.py` 已改为上传 API 的兼容入口。

## 测试

主机需要 Android SDK build-tools/35.0.0、platform android-35 或 android-36、Java：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q tests/test_service.py
```

使用真实签名 APK 和 fdroidserver，覆盖首次发布、更新、幂等重试、错误签名/版本/无效包拒绝、索引失败回滚、并发限制、Range 下载、旧下载持续有效、重启清理，以及内网 API 与下载入口隔离。

实现参考：[F-Droid 仓库流程](https://f-droid.org/en/docs/Setup_an_F-Droid_App_Repo/)、[FastAPI Request](https://fastapi.tiangolo.com/advanced/using-request-directly/)。
