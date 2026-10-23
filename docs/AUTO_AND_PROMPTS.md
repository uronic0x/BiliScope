# Auto、系统提示词与兼容 API / Auto, prompts and compatible APIs

## Auto 设置

“Auto 自动”页提供一个总开关。关闭后立即请求停止；新的分析步骤和发布会被拦截。已在途的网络请求或本地推理可能稍后完成，已发往 B 站的提交无法撤回。重启程序后总开关始终为关闭，不会依据上次会话状态自行发评。

| 设置 | 行为 |
| --- | --- |
| `recommendations` | 从 B 站推荐接口读取视频候选，选择未处理的有效 BV |
| `search` | 按用户填写的关键词搜索，选取未处理视频 |
| `queue` | 按固定队列顺序处理；每行一个 BV 或完整视频链接，可带 `?p=`；队列不接收短链 |
| 本机开始时间 | 留空立即开始；填写 HH:MM 后在本机时间等待，若今日该时刻已过则等明日；同一分钟内视为立即 |
| 运行时长 | 从计划开始时刻计算本次时段，结合单调时钟与本机时间检查截止；到期自动关闭，不无限追赶积压任务 |
| 常驻运行 | 勾选后忽略“运行时长”，只受手动关闭、每日分析额度和每日提交额度约束；适合“一直看推荐” |
| 间隔 | 本次视频处理完成后等待的分钟数；不会并发刷多个视频 |
| 最大视频数 | 本次最多处理的视频数；固定队列耗尽也会提前结束。常驻模式下不生效 |
| 自动发布 | 默认关闭，只分析并保存评论草稿；勾选后，本次 Auto 会直接发布通过检查的草稿，无须逐条弹窗。开启时会弹一次确认框 |
| 本次/每日提交上限 | 双重限制；每日采用本机日期，只统计 Auto 提交尝试，包含结果不确定的尝试 |
| 每日分析上限 | 每天最多分析多少个视频；常驻模式到额度后按小时轮询等待次日，避免无限刷推荐 |
| 先评分 | 分析后由应用固定评分规则打 1–10 分（与应用策略、视频证据分离）；低于阈值只记录，不写草稿、不评论、不 @ |
| 评分阈值 | 1–10；评分不可解析时按“未达标”处理（失败关闭），不会误发 |
| 只在达标时 @ 主人 | 评论照常发，但只有评分达标时才追加主人 @；与“@ 最短间隔”“每日 @ 上限”叠加生效 |
| 只 @ 主人，不写评论正文 | 不生成任何评论文字，只提交一条 `@主人`（需要同时开启“自动发布”和“@ 主人”）。适合“只想让人知道”，不想留下机器味评论 |
| 失败几次后放弃 | 单个视频可恢复错误的重试次数；达到后标记为已看并停止重试 |
| 失败冷却 | 可恢复错误后的退避起步分钟数，重复失败按 2 的幂递增，最多 8 倍 |
| 主人 UID | 自动 @ 的唯一目标。启动时验证，提交前再次验证昵称与 UID 绑定 |
| @ 最短间隔 / 每日 @ 上限 | 首条符合条件的评论可 @ 主人，此后须到达间隔，且每日不超过上限；冷却记录跨重启保留 |
| 处理结果列 | 显示状态、是否已 @ 主人（含平台确认情况）、评分和失败原因；悬停可看生成的草稿全文 |

推荐默认值：间隔 15 分钟、时长 60 分钟、最多 6 个视频、本次最多 3 条评论、每日最多 10 次提交、@ 间隔 30 分钟。先用关闭自动发布的模式核对生成效果，再按需要打开发布。

“一直看推荐、看到好看的再 @ 主人”的推荐配置：勾选“常驻运行”，来源选 `recommendations`，间隔 3–5 分钟，每日分析上限 30–60，勾选“先评分”并把阈值设为 6–7，同时勾选“只在达标时 @ 主人”，@ 最短间隔 60 分钟、每日 @ 上限 2–3。这样大多数视频只留在本地记录里，只有评分达标且额度允许的那一条才会通知主人。

单个视频的分析失败（网络、风控、无可用证据、抽帧失败等）不再终止整场会话：该视频不计入“已看”、不占视频配额，按失败冷却退避后重试，达到“失败几次后放弃”次数才标记为已看。登录失效、目标不一致、历史文件损坏、提交结果未知等情况仍会立即停止，因为它们意味着继续发布不安全。

@ 是当前视频下公开评论中的提及；不是私信，也不会单独每到一个时间点就另发一条消息。只有出现通过检查、且额度允许的新评论时才会提及主人。达到评论上限后仍可继续处理视频和保存草稿。平台返回缺少 @ 元数据时，本次会话暂停，请在 B 站核实；这不证明通知一定已送达。

运行期间编辑设置不会改变当前会话：来源、主人 UID、提示词、API 及发布权限在开启时冻结，下次开启时读取新配置。Auto 运行时，手动发评/切换视频任务被阻止，避免两个任务争用浏览器。应用保持打开即可运行；本版不安装 Windows 服务或计划任务，也不在程序关闭或机器关机时运行。

## 历史及运行记录

- `runtime/config/auto-plan.json`：计划；没有持久化的“已开启”状态。
- `runtime/state/auto-ledger.json`：已处理视频、发布尝试、主人提及冷却与每日计数、每日分析计数，以及失败视频的退避时间。
- `runtime/state/auto-session.json`：最近会话的状态、模式（timeboxed/always）与报告位置。
- `runtime/auto/<run-id>/report.json`：本次候选、评分、草稿、跳过原因、失败原因、提交结果和安全发现。
- `runtime/auto/<run-id>/requests/NNN-<purpose>.json`：每条实际请求的 **完整 messages 拼接** 与模型回复；图片以占位符省略，密钥、Cookie 与签名 URL 已脱敏。
- 同目录 `NNN-draft.json`：脱敏后的草稿记录。

## 评论为什么读起来像报告

评论任务和视频分析共用同一套“应用固定能力边界”，而分析用的第 4 条要求“保留时间点、说明缺失模态与未覆盖区间”。把这些要求带进评论任务，模型就会写出 `00:51 还是冷蓝色…` 这种带时间点和证据声明的观测记录，不像正常人留言。

因此评论任务现在使用独立的边界（不含时间点与覆盖率要求），并把任务范围写清楚：

- 只写一条评论，口吻像普通观众，不要总结/汇报/讲解；
- 不写时间点、不写“证据/模态/未覆盖/抽样/局限”、不声明只看了几帧；
- 你在“LOCAL USER POLICY”里写的“总结视频内容给主人”之类要求只用于分析，不适用于评论。

同时，传给评论任务的参考材料从“整篇分析报告”改为去掉了标题、加粗、引用块和独立时间戳的纯文本，避免模型照抄报告结构。这只是排版清洗，不做安全判断；参考材料仍然作为不可信证据传递。

如果仍觉得不自然，最直接的办法是勾选“只 @ 主人，不写评论正文”。

## 查看原始请求与提示词拼接

Auto 页的“查看原始请求”按钮会读取最近一次运行（或最近一次手动分析，目录名以 `manual-` 开头）的请求记录，按 `system → user → user` 原样展示发给模型的内容，包括：

- 应用固定能力边界 + 你的“LOCAL USER POLICY” + 当前任务约束（`system`）
- `LOCAL USER TASK: …`（分析任务）
- `untrusted_video_evidence` JSON，以及抽帧的时间点标记（`user`）

记录写在 `runtime/auto/<run-id>/requests/` 下，每次调用一个文件，文件名前缀即调用顺序。`purpose` 取值为 `analysis`、`analysis-frames`、`score`、`draft`。图片本身不落盘（只保留尺寸），因此记录很小；运行时最多保留 40 个运行目录的请求记录，单次运行最多 200 条 / 6 MB。

脱敏只作用于文本值，不会破坏 JSON 结构；`remember_secret` 会忽略长度不足 6 的“密钥”，避免把普通单词误替换成 `[REDACTED]`。

提交前先持久化一个“结果未知”的保留记录。遇到网络超时、崩溃、平台限制或 API 错误不会自动重发。结果未知也计入额度，且该视频不会被自动再次发评。按视频去重、@ 冷却、每日计数和失败退避都跨程序重启保留。历史损坏会停止 Auto，不会静默清空后继续发布。失败冷却记录仅用于跳过候选，不授予任何重发权限；清理它无法绕过提交去重。

已经保留过提交尝试的视频，即使换了一个分 P 也不会再自动评论，因为评论区属于同一个稿件。视频分析去重则按 BV + 分 P 记录。需要重新处理时，应先人工检查历史及 B 站状态；不要为了重试而直接删除未知提交记录。

## 系统提示词入口与预设

“系统提示词”页可选择预设，点击“载入预设”，编辑大文本框，然后保存。预设可同时用于视频分析和评论草稿。预设下方显示固定的应用能力边界，不能通过预设扩大工具权限。

| 预设 | 用途 |
| --- | --- |
| 严格证据与防注入 | 只依据证据，识别伪造身份、规则覆盖及泄密要求 |
| 学习笔记 | 整理问题、观点、时间点与复习要点 |
| 给主人汇报 / Owner update | 形成具体发现与证据限制；由程序添加主人 @ |
| 简洁客观 | 一句话加三条重点，评论只保留一个观察 |
| 事实核对视角 | 检查视频内部论据，避免谎称已联网核实 |
| 自定义 | 自行编辑；应用的固定能力边界仍然存在 |

系统提示词仅应包含行为策略。不要写入 API Key、Cookie、密码或其它凭据，因为系统提示词会发送给模型服务商。

预设不等于完整安全保证。提示词注入可能藏在字幕、图像和转写中；启发式检查可能漏报，也可能把讨论提示词安全的正常视频判为可疑。关闭“可疑指令时跳过发布”只关闭该启发式发布检查，不会开放模型的配置、发评、任意 URL 或文件操作权限。

### 代码中的权限边界

1. 标题、简介、字幕、ASR、图像、评论及已有模型分析只进入不可信证据消息，不被拼到 system/developer 消息中。观众评论默认不发给模型，可显式开启。
2. 模型最多能请求受数量、范围约束的 `capture_frames`。没有文件、Shell、网络跳转、配置修改或发布工具。
3. 发布由 Auto 控制器按冻结的本地计划发起。模型生成的 @、URL、疑似凭据、代码/结构化动作输出和超长文本会被挡下。目标视频须与已选择的有效 BV/分 P 一致。
4. 唯一自动提及目标来自用户的主人 UID，永远不从字幕、评论或模型输出中提取收件人。
5. 评分规则由应用固定，且与用户策略、视频证据分开；评分只决定“是否值得打扰主人”，不授予发布权限，解析失败按未达标处理。
6. 发布前及登录/身份验证之后再次检查停止信号和截止时间。请求结果未知不自动重试。

这些边界减少注入内容能触发的行为，并不能证明模型输出的语义必然正确。实际内容仍受模型质量、抽样覆盖和平台行为影响。

## OpenAI 格式兼容设置

本版使用 **Chat Completions**，向 `base_url` 下的 `/chat/completions` 发 POST；填写完整的 `/chat/completions` 地址也可。服务需要提供这一端点。

| 选项 | 配置方式 |
| --- | --- |
| API 地址、模型、Key | 自由填写；地址必须 HTTPS，本机 localhost 可用 HTTP |
| 图片输入 | 开启后使用 `content` 数组中的 `text` 和 `image_url`；关闭后发送普通文本 |
| function tools | 与图片开关独立；不支持工具的服务可以关闭，仍能用初次采样画面分析 |
| 提示词角色 | 可选 `system` 或 `developer`，由具体服务/模型能力决定 |
| 输出上限 | 可选 `max_tokens`、`max_completion_tokens`，或 `omit` 不发送该字段 |
| 超时 | 10–600 秒，可按服务调整；Auto 到期后不再启动后续步骤或发布 |
| 需要 Key | 无鉴权本机服务可关闭；空 Key 不发送 Authorization 头 |
| 额外 JSON | 例如 `{"temperature":0.2}`，或用户明确配置的 `thinking`、`reasoning_effort` 等专有选项 |

通用客户端默认不注入厂商专有字段。OpenAI / DeepSeek / local 快捷设置只是填写方便，模型名称仍可编辑；切换地址时界面清空原 Key，避免误用。选择 DeepSeek 快捷设置时，会在可见的额外 JSON 中填入关闭 thinking 的示例，可自行修改。OpenAI 快捷设置不替用户猜测模型名称。

额外 JSON 不能覆盖 `model`、`messages`、`tools`、`tool_choice`、`stream` 或 token 上限字段。工具调用需服务返回 `choices[].message.tool_calls`；兼容推理服务返回的 `reasoning_content` 仅在工具往返时保留，不展示为正文。

协议参考：[OpenAI Chat Completions](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions)。权限隔离参考：[Safety in building agents](https://developers.openai.com/api/docs/guides/agent-builder-safety)。

## English

Auto is a bounded or always-on, application-local session with a master ON/OFF switch, optional local HH:MM start, interval, duration, source selection (recommendations/search/queue), video limit, separate publication switch, session/daily attempt caps, a daily analysis cap and owner-only mention cooldown/limit. A queue accepts BV IDs/full URLs, including parts. Restart is always OFF. Keep the app running; no OS scheduler or service is installed.

"Run until switched off" removes the session deadline and video cap; only the stop switch and the daily analysis/attempt budgets bound it, so an unattended window cannot spin forever through the recommendation feed. Publication is OFF by default and is confirmed once per switch-on. Owner mentions occur only on eligible comments, not as separate timed private messages.

An optional quality gate scores each analyzed video 1-10 with an application-owned rubric that is kept separate from user policy and from untrusted evidence. Below-threshold videos are logged without a draft, without a comment and without a mention; an unparsable score also fails closed. "Mention only above threshold" keeps posting but omits the owner @ for weak videos, combined with the minimum interval and the daily owner-mention limit.

Recoverable per-video failures (network, risk control, no usable evidence, frame capture) no longer end the session: the video is not marked seen and is retried after an exponential backoff until the configured failure count is reached. Lost login, a destination mismatch, corrupt history and unknown submission outcomes still stop the session immediately. Persistent attempt reservations, deduplication, daily counters, backoff state and owner cooldown survive restarts; unknown outcomes are never automatically retried.

The Prompts tab provides five editable bilingual presets plus Custom. An application-owned capability boundary remains in effect. Evidence is kept out of privileged messages, comments are excluded by default, and the model has only bounded frame requests. The controller fixes destinations and permissions independently; generated mentions, links, credential patterns and action/code output fail the publication gate. Prompting and heuristics reduce risk; they cannot establish complete prompt-injection immunity.

Provider settings use OpenAI-compatible Chat Completions, with independent image/tool capability switches, system/developer role, max_tokens/max_completion_tokens/omit, optional authentication and visible extra JSON parameters. No vendor-specific fields are injected by default. See the tables and source references above for precise behavior.

Every outbound request is also written locally as `runtime/auto/<run-id>/requests/NNN-<purpose>.json`, containing the exact assembled `messages` and the model reply (`purpose` is `analysis`, `analysis-frames`, `score` or `draft`). Image payloads are stored as size markers only, and keys, cookies and signed URLs are redacted. The Auto tab's "View raw requests" button renders the latest run's assembly as `system → user → user`; manual analyses get their own `manual-*` folder. At most 40 run folders keep traces, 200 entries and 6 MB per run.

### Why the comments read like reports

Comment drafting reused the analysis capability boundary, whose clause 4 requires citing timestamps and disclosing missing modalities and uncovered ranges. Carried into a comment task, that produced comments like `00:51 still cold blue…` instead of something a viewer would write. Comments now use a separate boundary without those duties, and the task statement says explicitly that the comment is a public viewer comment, not a report to the owner, and that any earlier "summarise for the owner / cite timestamps / disclose coverage" policy applies to analysis only. The reference material is the analysis with headings, emphasis and standalone timestamps removed, so the model cannot copy the report's structure.

For "notify without writing a comment", enable "Mention the owner only, without comment text": no draft is generated at all and the submission body is just `@owner`. It requires both the owner mention and the publication switch, and still obeys the minimum interval, daily owner limit, session/daily attempt caps and the quality gate.
