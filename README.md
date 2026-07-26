# OldChat AstrBot Adapter

https://img.shields.io/badge/AstrBot-Plugin-blue
https://img.shields.io/badge/Python-3.9%2B-green
https://img.shields.io/badge/License-MIT-yellow

OldChat AstrBot 适配器 是一个完整的 AstrBot 平台插件，让你能够将 OldChat 聊天软件无缝接入 AstrBot，实现消息收发、群管理、红包、阅后即焚、朋友圈、签到等全功能集成。

支持官方 OldChat 服务以及任意第三方部署版本，只需配置服务器地址和 API 前缀即可。

---

✨ 功能特性

类别 支持的功能
基础消息 私聊/群聊文本、图片、文件、语音、视频收发
富文本 @提及、回复引用、图文混合
阅后即焚 发送阅后即焚消息（5/10/20/30/60/300秒）、开启焚毁
红包 发送群红包/私聊红包、查询红包详情、自动领取（可配置）
群管理 踢人、设置/取消管理员、转让群主、全员禁言、修改群名、发布群公告
朋友圈 发布图文动态、查看动态列表、点赞、评论
每日签到 手动签到、自动签到（可配置）、签到墙互动
社交互动 好友请求自动处理、加群请求自动审批、举报用户
公堂系统 查看案件、投票、提交陈述（部分功能已集成）
音乐广场 搜索音乐、点赞、评论、播放上报（可通过命令调用）
表情包 表情广场搜索、保存表情包
系统通知 查看系统通知列表
用户查询 查看自己的资料、查询任意用户信息、查看未读消息数
高度可定制 25+ 配置项，支持白名单、权限控制、自动行为开关

---

🚀 快速安装

1. 克隆插件

```bash
cd /path/to/AstrBot/data/plugins
git clone https://github.com/yourname/oldchat_astrbot.git
cd oldchat_astrbot
```

2. 安装依赖

```bash
pip install -r requirements.txt
```

3. 重启 AstrBot

```bash
# 使用 systemd
systemctl restart astrbot

# 或使用 Docker
docker restart astrbot
```

4. 在 Web 后台添加适配器

1. 打开 AstrBot Web 管理界面（http://你的IP:6185）
2. 进入 消息平台 → 新增适配器
3. 选择 oldchat
4. 填写配置（见下文）
5. 保存并启用

---

⚙️ 配置说明

在 AstrBot 后台的适配器配置页面，填写以下参数：

配置项 说明 示例
服务器基础地址 OldChat 服务器地址（不含路径） http://60.205.94.101:8080
API 路径前缀 API 路径前缀，官方为 /v1，根目录部署可填 / 或留空 /v1
用户名 登录用户名 mybot
密码 登录密码 ********
设备标识 任意唯一设备名 astrbot_ultimate
管理员 UID 列表 拥有管理权限的 UID，逗号分隔 UID-001,UID-002
群组白名单 只响应的群组，留空则全部 GRP-001,GRP-002
私聊白名单 只响应的用户，留空则全部 UID-001
红包默认金额 发送红包时默认总金额（金币） 100
红包默认份数 发送红包时默认份数 5
红包默认标题 红包默认标题文字 恭喜发财，大吉大利
自动领取红包 是否自动领取收到的红包（谨慎开启） 否
启用阅后即焚 是否启用阅后即焚功能 是
阅后即焚默认秒数 默认焚毁秒数（5/10/20/30/60/300） 10
自动通过好友请求 是否自动同意好友请求 否
自动处理入群请求 是否自动批准入群申请（需机器人有权限） 否
群聊回复时 @ 提问者 机器人回复群消息时是否自动 @ 对方 是
自动每日签到 是否每天自动签到 否
WS 最大重连间隔 WebSocket 断开后最大重连等待秒数 60
缓存刷新间隔 好友/群成员缓存自动刷新间隔（秒） 1800

---

📖 使用指南

基础命令

向机器人发送以下指令（私聊或群聊均可）：

命令 功能 权限
/oldchat 查看适配器状态 所有人
/oldchat me 查看自己的资料 所有人
/oldchat user <UID> 查询指定用户信息 所有人
/oldchat unread 查看未读消息数 所有人
/oldchat checkin 每日签到 所有人
/oldchat notices [数量] 查看系统通知 所有人

管理命令（仅管理员）

命令 功能
/oldchat redpacket send <目标ID> <金额> <份数> [标题] 发送红包（群或私聊）
/oldchat redpacket info <红包ID> 查询红包详情
/oldchat burn send <目标ID> <秒数> <内容> 发送阅后即焚消息
/oldchat burn <消息ID> 开启已收到的阅后即焚消息
/oldchat moment <内容> [图片URL] 发布朋友圈
/oldchat moment list [数量] 查看最近朋友圈
/oldchat groups 查看加入的群组列表
/oldchat members <群组ID> 查看群成员
/oldchat kick <群组ID> <用户UID> 踢出群成员
/oldchat setadmin <群组ID> <用户UID> <true/false> 设置/取消管理员
/oldchat transfer <群组ID> <新群主UID> 转让群主
/oldchat mute <群组ID> <true/false> 全员禁言/解禁
/oldchat groupname <群组ID> <新名称> 修改群名称
/oldchat announcement <群组ID> <公告内容> 发布群公告
/oldchat report <目标UID> [原因] 举报用户
/oldchat cache 手动刷新缓存（好友/群成员昵称）

---

🌐 自定义服务器地址

本适配器支持连接任意第三方 OldChat 部署版本，只需在配置中指定：

· 服务器基础地址：例如 https://oldchat.example.com 或 http://192.168.1.100:8080
· API 路径前缀：如果服务端 API 根路径是 /v1，则填 /v1；如果是根目录，则填 / 或留空。

WebSocket 地址自动由 server_base_url 转换（http→ws, https→wss）并拼接 /ws。如果您的 WebSocket 地址特殊，欢迎提 Issue 反馈，我们可以增加 ws_url 配置项。

---

❓ 常见问题

Q1：适配器无法启动，握手失败？

检查 server_base_url 和 api_prefix 是否正确组合，例如官方地址是 http://60.205.94.101:8080/v1/auth/handshake，如果填写错误会导致 404。

Q2：如何获取自己的 UID？

向机器人发送 /oldchat me，返回信息中的 UID 即为您的 UID。将其填入管理员列表即可获得管理权限。

Q3：如何获取群组 ID？

发送 /oldchat groups，机器人会列出所有群组及其 ID（格式如 GRP-xxx）。

Q4：自动领取红包安全吗？

自动领取红包会立即领取所有收到的红包，可能导致机器人币被消耗。建议仅在测试环境开启，生产环境保持关闭。

Q5：机器人不响应某些群/用户？

请检查群组白名单和私聊白名单配置，确保目标 ID 在白名单内，或留空以允许所有。

---

🛠️ 开发与贡献

欢迎提交 Issue 和 PR。

本地开发

```bash
git clone https://github.com/yourname/oldchat_astrbot.git
cd oldchat_astrbot
# 修改代码后，重启 AstrBot 即可加载
```

项目结构

```
oldchat_astrbot/
├── metadata.yaml               # 插件元数据（配置项定义）
├── oldchat_client.py           # OldChat API SDK
├── oldchat_platform_adapter.py # AstrBot 平台适配器
├── main.py                     # 插件入口（命令处理器）
├── oldchat_event.py            # 事件定义
├── requirements.txt            # 依赖
└── README.md                   # 本文档
```

---

📄 许可证

本项目采用 MIT License，可自由使用和修改。

---

🙏 致谢

· AstrBot - 强大的聊天机器人框架
· OldChat 团队 - 提供优秀的聊天平台

---

⭐ 如果这个项目对你有帮助，欢迎给个 Star！
