# LiveContainer + SideStore Nightly AltSource

这是供 AltStore Classic 和 SideStore 使用的第三方软件源，仅收录 LiveContainer 官方 Nightly 发布的组合版 `LiveContainer+SideStore.ipa`。

## 添加软件源

在 AltStore Classic 或 SideStore 的 **Sources** 页面添加以下地址。

```text
https://raw.githubusercontent.com/saki3525/livecontainer-altsource/main/altstore/source.json
```

Nightly 使用固定下载链接，上游发布新构建时会替换文件，因此源里只列出当前可下载的版本。安装包由 [LiveContainer 官方 GitHub Release](https://github.com/LiveContainer/LiveContainer/releases/tag/nightly) 提供。

## 更新软件源

GitHub Actions 每 6 小时检查一次（UTC 00:23、06:23、12:23、18:23）。也可以在 **Actions → Update AltSource → Run workflow** 手动触发。只有 `altstore/source.json` 有变化时才会提交。

生成器使用 GitHub Release 的发布时间和官方资产元数据，并下载 IPA 核对字节数和 SHA256。版本、构建号、软件包标识和最低系统版本来自组合版主应用的 `Info.plist`。官方 `apps_nightly.json` 提供图标和权限等信息。

本地运行需要 Python 3.11 或更新版本，使用标准库即可。

```sh
python -B -m unittest discover -s altstore
python altstore/generate.py
```
