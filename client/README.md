# Android 客户端更新修复

本目录维护 Droid-ify 的更新状态修复补丁。上游固定为 `upstream.json` 中的
v0.7.8 提交；补丁和派生 Android 代码遵循 GPL-3.0-or-later，完整许可证见
`LICENSE`。保留 Droid-ify、FoxyDroid 和上游贡献者署名。Store 服务端继续使用 MIT。

## 行为

- 安装、更新、卸载或仓库数据变化后，刷新已有的“有可用更新”通知；没有剩余更新就撤销。
- 手动安装和自动更新使用同一通知逻辑。用户划掉的通知不会因普通数据库变化重新弹出。
- 同步结果为空、关闭更新通知，以及商店更新自身后，清理旧通知；列表变化仅更新内容，不重复响铃。
- 打开商店或从后台返回主界面时检查仓库。五分钟内不重复请求；刚同步过的仓库、离线状态和全部禁用的仓库不触发请求。
- 前台检查使用正常的条件请求，保留 ETag 和 Last-Modified；手动强制刷新仍可用。
  前台检查独立于后台自动同步选项，后台原有网络条件和周期保持不变。

## 准备和验证源码

需要 Python 3.12、Git、JDK 21、Android SDK platform android-37.1 和
build-tools 36.0.0。首次运行 Gradle 需要下载依赖。

```bash
python3 scripts/prepare_client.py
# 上一条命令最后一行是准备好的源码目录，进入该目录：
./gradlew --no-daemon --no-configuration-cache --max-workers=2 \
  -Pkotlin.compiler.execution.strategy=in-process \
  '-Dorg.gradle.jvmargs=-Xmx3g -XX:ActiveProcessorCount=4' \
  :app:testDebugUnitTest :app:assembleRelease
```

默认仅应用更新修复，保留原版包名和默认仓库。已有定制客户端可将本地定制补丁
通过 `--customization-patch /path/to/local-branding.patch` 传入。公开仓库不存放实际
部署配置、应用签名材料、APK、设备报告或截图。所有构建输出放在 `.local/` 或仓库外。
脚本不会重置已有工作区；检测到源码被修改时会停止，避免覆盖其他工作。

例如，为已有定制版本准备后续升级：

```bash
python3 scripts/prepare_client.py \
  --customization-patch /path/to/local-branding.patch \
  --version-name 1.0.1 --version-code 2 \
  --archive .local/client/corresponding-source.tar.gz
```

归档包含完整已修改源码、上游许可证、原始补丁和合并后的 `recipe/applied.patch`。
解压后可在源码根目录直接执行上面的 Gradle 命令；也可克隆固定上游提交，应用
`recipe/applied.patch` 重建相同源码。归档不包含 `.git`、Gradle 缓存或签名私钥。

回归测试覆盖手动安装后剩余更新数量与通知撤销、启动时清理旧通知、关闭通知、
用户划掉通知后的行为，以及前台检查节流、离线重试和条件请求保留。
测试使用合成包名和本地模拟，不连接实际仓库或设备。

## 商店更新自身

客户端按 Android 包名和版本识别更新，因此也能从仓库更新自身。新版必须保持原
`applicationId`、沿用原应用签名并提高 `versionCode`。使用既有签名材料对 release APK
执行 zipalign 和 apksigner；签名后的最终 APK 与对应完整源码一起按部署流程发布。
不要生成新密钥覆盖已有身份。普通应用与商店自身使用相同的仓库发现流程，商店自身排在批量更新最后。

上传新版后，旧商店通过打开应用、手动同步或后台同步发现更新。
**仍在运行的旧版本不会提前拥有本次新增的“进入前台自动检查”行为**，首次升级可手动同步。
安装确认或静默更新是否可用，继续由 Android 版本和选用的安装器决定。

准备源码、构建和推送源代码不会自动上传 APK、修改仓库索引或部署服务。
