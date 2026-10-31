# 开源分发方案调研

调研日期：2026-10-24。资料来自项目官方文档与源码仓库，尚未部署或进行代码审计。功能描述与维护状态可能变化，实施前需再次确认。

## 1. F-Droid 自建仓库：优先验证

F-Droid 支持独立于官方仓库的自建应用源，可以直接托管已经编译的 APK，无需把应用提交到官方商店，也无需在仓库服务器重新编译应用。官方仓库的收录政策与自建仓库是两件事。

基础发布流程：

1. 安装 fdroidserver 工具，使用 `fdroid init` 初始化仓库及仓库签名密钥。
2. 将已签名 APK 放入 `repo/`，填写应用元数据。
3. 执行 `fdroid update` 生成索引。
4. 将仓库内容发布到 HTTPS 服务。
5. 手机客户端添加仓库，通过仓库发现应用和更新。

适合本项目：集中管理自有 APK，复用仓库索引和客户端生态；发布流程可进一步接入 CI。仓库签名密钥与各应用 APK 签名密钥应分别妥善管理。

来源：https://f-droid.org/en/docs/Setup_an_F-Droid_App_Repo/

## 2. Droid-ify：现成 Android 客户端

Kotlin 编写的开源 F-Droid 客户端，可作为验证自建仓库的现成客户端。后续可以评估定制名称、图标和默认仓库；这些定制的实现成本尚未核实。

项目采用 GPL-3.0，修改后分发应遵循许可证。GitHub 仓库标记为 Codeberg 的镜像，后续开发应确认上游位置。

来源：https://github.com/Droid-ify/client

上游：https://codeberg.org/droidify/client

## 3. Obtainium：统一更新管理的替代路线

直接从 GitHub 等应用发布来源获取 Android 应用更新。若主要需求是集中检查现有 Releases 的更新，可以评估此方案。

它侧重更新管理，与展示自有应用目录、提供品牌商店的目标存在差异。批量导入、私有来源和国内网络表现需要实际验证。项目采用 GPL-3.0。

来源：https://github.com/ImranR98/Obtainium

## 4. fdroid-store：带管理界面的候选服务端

项目文档列出了自托管 F-Droid 仓库、网页商店、公有与私有应用、APK 上传，以及 GitHub、GitLab、Gitea/Forgejo 发布包自动获取等功能。采用 MIT 许可证。

功能贴近发布后台需求，但调研时项目规模较小，成熟度、安全性、部署成本和长期维护情况尚未验证，不建议未经试用直接作为核心依赖。

来源：https://github.com/Dim145/fdroid-store

## 5. Selfdroid：不优先采用

提供自托管 Android 应用分发 Web 服务，但仓库已于 2025-01-02 归档，因此暂不作为新项目首选。

来源：https://github.com/vitlabuda/selfdroid-web-app

## 建议与待定事项

建议先验证 F-Droid 自建源 + Droid-ify，验证成功再决定品牌客户端及管理后台的实现方式。不要在验证之前从零编写下载、仓库协议和更新管理系统。

尚待确认：面向内部还是公开用户、APK 存储与下载域名、发布方式、是否需要访问控制、是否必须独立品牌客户端。当前不需要这些答案即可整理文档；正式部署时应确定。
