# Clash 网站规则

点击 Chrome 工具栏扩展，将当前网站添加为直连、阻止或已有代理组规则。保存前自动备份配置，加载失败会回滚。

支持：

- macOS：ClashX Pro
- Windows 10/11：Clash for Windows 0.20.x

## 安装

先下载并解压本仓库。在 Windows 上请保留整个解压目录，不要只保存 `extension` 文件夹。

### Windows / Clash for Windows

1. 安装 [Python 3](https://www.python.org/downloads/windows/)，安装时勾选 `Add Python to PATH`。
2. 启动 Clash for Windows，并选择一个常规 YAML Profile。
3. 双击 `install.cmd`。它会在当前用户目录安装本地辅助程序，并登记 Chrome Native Messaging；不需要管理员权限。
4. Chrome 打开 `chrome://extensions`，开启「开发者模式」。
5. 点击「加载已解压的扩展程序」，选择本项目的 `extension` 文件夹。
6. 在工具栏拼图菜单中固定「Clash 网站规则」。

安装程序会从 `%USERPROFILE%\.config\clash\config.yaml` 自动读取 CFW 的 Controller 地址和 secret。CFW 开启随机 Controller 端口也可以使用。

### macOS / ClashX Pro

1. 双击 `install.command`（需要 Python 3，仅使用标准库，无需 pip）。
2. Chrome 打开 `chrome://extensions`，开启「开发者模式」。
3. 点击「加载已解压的扩展程序」，选择本项目的 `extension` 文件夹。
4. 在工具栏拼图菜单中固定「Clash 网站规则」。

扩展带固定公钥，在不同电脑和目录中的扩展 ID 一致。

## 使用

打开网站 → 点击扩展 → 检查域名和匹配范围 → 选择访问方式 → 添加并立即生效。

例如在 `www.cc98.org` 页面，将域名改成 `cc98.org`，选「该域名及全部子域名」和「直连」，即可同时覆盖首页、API 等子域名。默认保留当前完整域名，避免错误推断主域名。

- 同一域名、同一匹配类型再次添加会更新其策略，并置于规则最前面。
- 删除只移除扩展管理的规则，原配置中已有规则保持不变。
- 订阅更新后若规则被覆盖，点击「重新应用」。
- 自定义规则集合全局共享；切换 Profile 后，点击「重新应用」可写入当前配置。
- Clash 必须处于规则模式。网页可能需要刷新；已建立的连接不会被强行断开。
- 仅支持包含小写 `rules:` 常规列表的 Clash YAML；不支持内联列表、别名和 IP 地址输入。

## Windows 配置识别

CFW 没有提供“当前 Profile 文件路径”的 Clash API。扩展会将运行时的前 300 条规则与 `profiles` 目录中的 YAML 比较，只在唯一匹配时修改文件。无法唯一识别时不会猜测，也不会改动配置。

遇到识别提示时，在 `%LOCALAPPDATA%\ClashSiteRule\settings.json` 的 `profile_path` 中填写当前 Profile 的完整路径，例如：

```json
{
  "profile_path": "C:\\Users\\your-name\\.config\\clash\\profiles\\123456.yaml"
}
```

在 CFW 的 Profiles 页面右键当前配置并选择「Edit in text mode」，可以看到文件路径。若使用便携版或改过 Home Directory，可设置 `clash_home`。也可手动设置 `controller`，格式为 `127.0.0.1:9090`。

## 数据与恢复

- macOS：`~/Library/Application Support/ClashSiteRule/`
- Windows：`%LOCALAPPDATA%\ClashSiteRule\`

其中 `rules.json` 保存扩展规则，`backups` 保存每次应用前的完整配置，`settings.json` 保存本机连接设置。备份可能含订阅凭据，请勿公开。

配置原文只插入一个带标记的规则块，其他内容不重新格式化。应用后会检查运行时规则；重载失败会还原文件并尝试重新加载原配置。

## 卸载

先在扩展中删除保存的规则，再从 Chrome 移除扩展。

- macOS：删除 `~/Library/Application Support/ClashSiteRule` 和 `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/local.clash_site_rule.json`。
- Windows：删除 `%LOCALAPPDATA%\ClashSiteRule`，并删除注册表 `HKCU\Software\Google\Chrome\NativeMessagingHosts\local.clash_site_rule`。

## 开发验证

```sh
python3 -m unittest discover -s tests -v
```

权限仅 `activeTab` 和 `nativeMessaging`；不读取网页正文、浏览历史或登录信息，不运行网页脚本，不开放网络监听端口。桥接采用 [Chrome 官方 Native Messaging 协议](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)，只接受本扩展来源。
