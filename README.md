# BiliScope

> B 站视频 AI 助手 — 字幕/抽帧理解、带时间点问答、评论草稿与发布、定时 Auto 无人值守看推荐叫主人。本地 Whisper 转写，OpenAI 兼容 API，Patchright 独立浏览器。CN / EN 双语界面。

[Auto · 提示词 · API 说明](docs/AUTO_AND_PROMPTS.md) · [English](README_EN.md) · [运行文件控制](docs/RUNTIME_POLICY.md) · [依赖及来源](THIRD_PARTY_NOTICES.md) · [验证记录](docs/VALIDATION.md)

## 快速开始

1. 安装 **CPython 3.12+**（64 位，需含 Tcl/Tk；3.13 / 3.14 也可）
2. 解压到可写目录，双击 `install.bat` — 自动建 `.venv`、装固定版本依赖（SHA-256 校验）、下载官方 Chromium
3. 双击 `launch.bat`，在设置页填 API Key（默认 DeepSeek，也支持其它 OpenAI 兼容地址）
4. 扫码登录 B 站，输入 BV 号或视频链接，点"分析视频"

ZIP 不附带浏览器、虚拟环境或模型——避免混入个人状态和不明可执行文件。安装所需的版本与校验值固定在 `requirements.lock`、`docs/browser-lock.json` 和 `docs/model-lock.json`。

## 功能

- **视频分析** — 优先获取带时间戳字幕；无字幕时本地 Whisper base 转写（CPU，首次约 160 MB）。视觉模型接收抽样画面，可按问题补看指定时刻。默认分析前 30 分钟（可改 1–120）。无字幕/转写/画面时不凭标题臆测。
- **定时 Auto** — 推荐/搜索/队列来源，评分门控只处理高质量视频；主人 UID 自动 @，可选无人值守自动发布。失败退避重试不中断整场。重启不自动恢复发布。
- **系统提示词** — 五套预设（严格防注入 / 学习笔记 / 给主人汇报 / 简洁客观 / 事实核对）+ 自定义。载入后可编辑保存。
- **评论与 @** — 草稿生成、预览发送、按 UID 添加 @（最多 5 位，重名/重复拒绝）。提交前重新核实登录与昵称。相同内容不重复提交，间隔至少 15 秒。
- **隐私** — Key 默认仅内存，可选 DPAPI 加密保存。所有文件在项目目录内，不碰系统环境变量/注册表。无遥测。

## 安全边界

- 字幕、评论、图像等只作为不可信证据传给模型，不进入 system/developer 消息
- 模型仅有受限的抽帧工具，无文件 / Shell / 网络 / 配置 / 发布权限
- 自动 @ 目标只来自用户填写的 UID，不从内容中提取
- 发布前检查注入模式、凭据模式和已知密钥；结果未知不自动重试
- 评分规则由应用固定，不可被提示词覆盖

详见 [Auto、提示词与 API 说明](docs/AUTO_AND_PROMPTS.md)。

## 目录

| 路径 | 内容 |
| --- | --- |
| `biliscope/` | 应用源码（19 个模块） |
| `docs/` | 文档、依赖来源与许可证 |
| `tests/` | 单元 / 集成 / UI 测试 |
| `runtime/` | 运行时数据（日志/缓存/模型/配置）— 不入库 |
| `.venv/` | Python 依赖 — 安装后生成，不入库 |

## 测试

```bat
.venv\Scripts\python.exe -I -B main.py --test
```

43 项测试，42 通过 1 跳过。详见 [验证记录](docs/VALIDATION.md)。

## 排查

`doctor.bat` 生成诊断报告（仅路径，不含 Key/Cookie）· 日志见 `runtime/logs/` · TLS 校验始终启用

## License

MIT。第三方库/浏览器/模型各自保留许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
