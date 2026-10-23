# 运行文件位置控制 / Runtime file policy

## 约束及边界

应用创建的虚拟环境、设置、凭据密文、浏览器配置、浏览器安装、模型、证据、导出、临时媒体及日志都在项目根目录内。主入口先配置路径，再导入第三方依赖。所有相对应用路径从源码位置推导，不使用启动终端的工作目录。

这不是操作系统强制沙箱。Python audit hook 拦截普通 Python 文件写入、目录创建、删除、重命名、硬链接和修改属性，并禁止应用创建符号链接。原生代码、子进程、Windows Known Folder API 和操作系统自身行为不能由该 hook 全面约束。浏览器与依赖采用下列额外配置。

Windows 可能自行记录事件日志、Prefetch、Defender 扫描、DPAPI 用户主密钥、页文件或驱动缓存。这些属于平台行为，不能承诺项目外绝对零写入。程序不安装服务、计划任务，不注册全局浏览器，不修改系统环境或注册表。

## 入口及路径

- `install.bat`：在解压目录启动 `bootstrap.py`；`.venv` 使用复制而非链接方式建立。pip 只往该环境安装，使用固定 wheel 哈希、禁止源包构建及字节码编译。下载缓存、安装报告及日志显式放进项目。
- `launch.bat`：使用本项目解释器，传入 `-I -B` 隔离用户站点并关闭字节码；控制台输出重定向至 `runtime/logs/console.log`，每次启动覆盖。
- 直接启动：`main.py` 首先调用 `configure()`，切换到项目目录、禁用字节码并安装 Python 写入检查。推荐仍使用启动脚本以隔离解释器启动阶段的用户扩展。
- 已存在的运行目录如果通过 symlink/junction 指向项目外，会被拒绝。实际运行配置及缓存路径必须位于项目根目录之下。

| 项目 | 位置/控制 |
| --- | --- |
| Python tempfile、TEMP、TMP、TMPDIR | `runtime/tmp/` |
| pip | `runtime/cache/pip/`；禁用版本检查，禁止外部 pip 配置 |
| 浏览器配置 | `runtime/browser-profile/`；不选用全局 Chrome/Edge profile |
| 浏览器安装 | `runtime/browsers/chromium-<固定快照号>/`；显式 executable_path |
| 下载/临时音视频 | `runtime/downloads/`；下载大小上限，完成/取消后清理 |
| Chromium 缓存 | `runtime/cache/chromium/`；磁盘缓存 128 MiB、媒体缓存 64 MiB（浏览器参数是提示值，非磁盘配额） |
| 崩溃/日志/trace | `runtime/logs/`；禁用正常崩溃上报及浏览器日志，仍指定回退路径 |
| AppData、LocalAppData | 本进程及子进程环境中重定向到 `runtime/appdata/` 与 `runtime/localappdata/` |
| XDG data/config/cache/state/runtime | `runtime/` 相应子目录；Linux runtime 目录权限 0700 |
| Hugging Face、Torch、Numba、CUDA 缓存 | 重定向至 `runtime/cache/`；本应用默认不安装 Torch 或 CUDA |
| Node 缓存/历史 | `runtime/cache/node/`、`runtime/state/node-history` |
| API Key | 默认内存；可选 `runtime/config/api-key.dpapi` |
| 登录状态 | 由本项目浏览器 profile 管理，不写独立 Cookie 导出文件 |
| 应用日志 | `runtime/logs/app.log`；2 MB × 当前文件与 3 份历史；已知 Key、Bearer、Cookie 及带查询参数的 URL 脱敏 |

继承的浏览器路径/下载源覆盖、Node 启动注入、调试日志开关和 TLS key log 路径会被清除。没有修改 HOME 或 USERPROFILE。环境调整只影响当前应用及子进程，退出后不改变系统设置。

## Auto 与提示词数据

Auto 计划和自定义系统提示词保存在 `runtime/config/`；去重、发布保留记录和主人提及冷却保存在 `runtime/state/auto-ledger.json`；各次运行的报告、草稿及错误状态保存在 `runtime/auto/<run-id>/`。所有写入仍经项目路径检查。Auto 使用应用内计时器，重启默认关闭，不创建 Windows 服务、任务计划或项目外日志。模型只拥有抽帧工具，不能发起配置或文件操作。

## 网络及遥测

应用没有行为统计、Sentry 或遥测 SDK。Chromium 禁用后台联网、组件更新、同步、Breakpad、崩溃上报和部分后台服务，并拦截常见第三方分析域名。模型相关依赖使用 `DO_NOT_TRACK` / `HF_HUB_DISABLE_TELEMETRY` 等进程环境设置；应用模型下载器本身使用标准 HTTPS，不安装 Hugging Face SDK。

不能把启动参数等同于“整个浏览器永不联网”。B 站页面本身仍有自身请求。正常目标包括 B 站及 CDN、用户设置的模型 API；安装/首次模型获取还需 PyPI、官方 Chromium 存储和 Hugging Face 模型存储。所有 HTTPS 保留证书校验；不设置 `NODE_TLS_REJECT_UNAUTHORIZED=0`，不使用忽略 HTTPS 错误的浏览器选项。

## 诊断和清理

“运行目录”页及 `doctor.bat` 提供实际路径报告。它检查应用配置路径，**不能替代 Windows Process Monitor 的真实文件写入追踪**。安装后 `runtime/provenance/` 保存版本、源码链接、下载记录与二进制哈希。

关闭所有本项目进程后，可删除 `runtime/tmp/` 和 `runtime/downloads/` 中的残留文件。`runtime/cache/` 可清理，之后安装器可能重新下载。清理 `runtime/models/` 会触发重下模型；清理 `runtime/browser-profile/` 会退出网站登录。重建虚拟环境前先关闭程序。

## English

Application-managed files are kept beneath the project root. Startup configures process-local temp/cache/profile paths before third-party imports, disables Python bytecode, rejects ordinary Python filesystem writes outside the root and refuses symlink escapes. Pip installs only pinned, hashed binary wheels into `.venv`; Chromium receives an explicit executable and profile location.

The Python audit hook does not sandbox native libraries or child processes. Explicit paths are therefore also provided to Chromium and native dependencies. OS-managed files (event logs, antivirus, Prefetch, DPAPI master keys, paging and driver caches) are outside this application policy. No global environment/registry edits, services or scheduled tasks are installed.

Telemetry is disabled where configurable, but Bilibili pages still make their own network requests. Certificate verification remains on. The diagnostics report verifies configured paths; it is not a substitute for a Windows filesystem trace. This delivery includes no claim that a Windows-wide zero-write trace has been completed.
