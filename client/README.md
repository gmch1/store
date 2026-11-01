# Ming Store Android 客户端

客户端基于固定的 Droid-ify v0.7.8，以独立补丁维护。上游来源见 `upstream.json`，
我们的补丁按 `patches/series.json` 顺序应用。Android 衍生代码采用 GPL-3.0-or-later，
保留 Droid-ify、FoxyDroid 署名，许可证见 `LICENSE`；构建脚本和服务端采用 MIT。
完整的归属和公开边界见 [项目结构](../docs/project-layout.md)。

## 固定结构

- `upstream.json`：上游地址、标签和精确提交；不放部署配置。
- `release.json`：我们的公开包名、版本名和 versionCode。
- `patches/ming-store.patch`：名称、图标、署名、单仓库首次初始化和默认偏好。
- `patches/update-state.patch`：更新通知刷新、前台同步和相关回归测试。
- `../scripts/client_config.py`：读取并校验配置，区分可嵌入客户端的值和签名文件引用。
- `../scripts/prepare_client.py`：创建独立上游工作目录、应用补丁、生成连接配置。
- `../scripts/build_client.py`：统一执行测试、release 构建、签名核对和完整源码归档。

上游源码、构建缓存和交付物全部在 `.local/client/`；无需把完整上游复制进公开 Git。

## 一次配置

需要 Python 3.12、Git、JDK 21、Android SDK `platforms;android-37.1` 和
`build-tools;36.0.0`，设置 `ANDROID_HOME`。首次构建会下载 Gradle 和依赖。

```bash
cp .env.client.example .env.client
chmod 600 .env.client
# 编辑 .env.client，填入实际仓库信息和已有签名的证书指纹。
python3 scripts/build_client.py
```

`.env.client` 被 Git 忽略。也可以直接导出同名环境变量；环境变量优先于文件。
支持 `--env-file /path/to/private.env` 指定其他本地配置文件。文件采用字面量
`KEY=value` 格式，支持引号和注释，不执行 shell 命令。

| 变量 | 用途 | 是否进入 APK/完整源码 |
| --- | --- | --- |
| `STORE_CLIENT_REPO_URL` | 默认 F-Droid 仓库 HTTPS 地址 | 是，客户端必须知道下载地址 |
| `STORE_CLIENT_REPO_FINGERPRINT` | 仓库证书 SHA-256 指纹，64 位十六进制 | 是，用于校验仓库身份 |
| `STORE_CLIENT_SOURCE_URL` | 设置页中的本客户端源码地址，默认本项目 GitHub | 是 |
| `STORE_CLIENT_SIGNING_DIR` | 已有签名目录，默认 `~/.local/share/ming-store/signing` | 否 |
| `STORE_CLIENT_KEYSTORE` / `STORE_CLIENT_PASSWORD_FILE` | 可选的独立密钥和密码文件路径 | 否 |
| `STORE_CLIENT_KEY_ALIAS` | 已有签名别名，默认 `ming-store` | 否 |
| `STORE_CLIENT_CERTIFICATE_SHA256` | 预期的应用签名证书指纹，签名前后均核对 | 否，仅用于构建校验 |
| `STORE_CLIENT_ANDROID_HOME` / `STORE_CLIENT_GRADLE_USER_HOME` | 可选的客户端 SDK 和缓存路径，优先于通用环境变量 | 否 |

私有化指实际部署配置不进入 Git。前三项是 APK 运行必需的公开信息，可从 APK 中读取；
上传 API Key、DNS Token 和签名密码属于服务端或签名文件，不属于客户端连接配置。
解析器会拒绝把服务端密钥字段放进客户端配置文件。
默认仓库只在首次建库时写入；修改构建环境变量不会覆盖已有用户的仓库设置、禁用状态或删除操作。

签名文件保持原位置，脚本只引用和使用已有文件，不自动创建或替换签名身份。
仓库签名与 APK 应用签名是两个独立身份。后续升级保持包名、应用签名，并提高
`client/release.json` 中的 `versionCode`。

## 构建与交付

```bash
# 仅准备源码，最后一行输出源码目录：
python3 scripts/build_client.py --prepare-only
# 完整测试、构建、原签名签署和源码归档：
python3 scripts/build_client.py
# CI 或公开复现：只使用合成配置，不读取签名文件：
python3 scripts/build_client.py --example-config --unsigned
```

输出到 `.local/client/dist/`：版本化 APK、以最终 APK SHA-256 命名的完整源码
`.tar.gz` 和 `release.json`。源码归档包含完整上游源码、许可证、实际应用的合并补丁和
生成的公开连接配置，解压后可直接执行 Gradle 构建，不依赖原部署者的 `.env.client`。
归档不复制本地配置文件、签名材料、`.git`、构建缓存或设备报告。

解压完整源码后，在源码根目录执行以下命令即可重建未签名 APK，无需 `.env.client`：

```bash
./gradlew --no-daemon --no-configuration-cache --max-workers=2 \
  -Pkotlin.compiler.execution.strategy=in-process \
  '-Dorg.gradle.jvmargs=-Xmx3g -XX:ActiveProcessorCount=4' \
  :app:testDebugUnitTest :app:assembleRelease
```

同一上游、补丁、版本和公开连接配置复用同一准备目录；任一项变化会新建目录。
脚本拒绝覆盖已有源码编辑，并在编译后重新校验源码和构建配方。
`--upstream-cache /path/to/local/upstream` 可复用本地上游克隆；`--jobs` 限制并发。

若只想研究原版上的更新修复，可执行
`python3 scripts/prepare_client.py --upstream-only`。这会保留原版包名和默认仓库。

## 更新行为

安装或仓库数据变化后，更新已有通知中的剩余应用；没有更新就撤销。用户划掉的通知
不会因普通数据库变化重新弹出。商店自更新后也会清理旧通知。
打开或返回商店主界面时检查仓库，五分钟内不重复请求；离线、全部仓库禁用或刚同步过时跳过。
前台检查保留 ETag/Last-Modified，独立于后台自动同步周期和网络选项。

客户端可以更新自身：将原包名、原签名、更高 versionCode 的新版 APK 及对应完整源码
发布到应用仓库即可。旧版本首次发现更新可手动同步；安装确认或静默安装由 Android
及选用的安装器决定。源码推送和本地构建都不自动修改线上仓库或部署服务。
