# 验证记录 / Validation record

Date: 2026-10-22. Host: Linux container, CPython 3.12.14. Target platform: Windows x64. Updated for source release 1.2.0. This revision adds unattended-watching behaviour; it was re-run on Windows with CPython 3.14 (main.py --test).

## Completed

- Created the isolated project-local `.venv`; installed the eight fixed dependencies using wheel-only installation and `--require-hashes`.
- Resolved and downloaded the complete Windows x64 / CPython 3.12 wheel set with the same lock and verified hashes. Windows package binary/license inventories are included in `windows-wheel-audit.json` and `source-manifest.json`. Standard CPython 3.13/3.14 wheel availability was checked in the published metadata; those interpreters were not executed.
- Downloaded official Windows and Linux Chromium snapshot archives, verified their SHA-256 and recorded the corresponding upstream source commits and REVISIONS. No Chrome/Edge/Chrome-for-Testing binary is bundled in the deliverable.
- Installed the pinned Linux Chromium archive entirely inside the project.
- Ran the automated suite: **43 tests; 42 passed; 1 skipped because the host blocked Chromium launch**.
- Tested URL/part validation, media frame budgets, WBI reference signing and Unicode percent encoding, explicit mention UID mapping, top-level reply normalization, API model modality, response truncation, bounded frame-tool message order, title-only evidence rejection archive traversal/symlink rejection, and no automatic retry after an unknown comment outcome.
- Tested an externally started process with hostile inherited temp/cache/AppData/browser paths: all configured paths redirected into the project. Ordinary Python writes outside the project, traversal and symlink creation were denied. Tested temporary-file location and log-secret redaction.
- Generated a real encoded red/green/blue video, decoded its frame at 2.5 seconds with PyAV, and verified the timestamp and green pixel values.
- Downloaded and SHA-256-verified all three pinned Whisper base model files. Ran **real CPU inference** on the upstream model repository's short English sample. It returned a nonempty English transcript with an approximate 0.00–6.62 second chunk range. The host emitted a CPU-info warning because `/proc/cpuinfo` was restricted, but inference completed.
- Parsed all delivered Python source and checked the ZIP for unintended runtime/credential/binary contents.

## v1.1 additional checks

- Virtual-clock Auto tests cover periodic owner mentions, session and daily caps, draft-only mode, planned time calculations, stop and expiry during analysis and immediately before POST, frozen owner/publish configuration, wrong-video rejection and persistent unknown-outcome reservations.
- Verified owner mention cooldown survives a restart. Auto enabled state is not persisted.
- Tested malicious evidence remaining outside system/developer messages, comment exclusion by default, malicious generated @/links being blocked, and extra JSON being unable to replace messages or tools.
- Tested a keyless local-compatible provider, developer role configuration, max_completion_tokens, tools disabled independently of images, and absence of default vendor-specific request fields.
- Tested source candidate parsing ignores external links and invalid BV identifiers. The browser publish boundary rejects a stop signal received during its awaited login check.

## v1.2 unattended-watching checks

- Tested that a recoverable per-video failure (`BILI_API`) keeps the session running, leaves the video unmarked for a later retry, and does not consume the video quota; the next candidates are still submitted.
- Tested that repeated failures apply an exponential backoff window and that a video reaching the configured failure count is abandoned and marked seen.
- Tested that fatal codes (`LOGIN_REQUIRED`, `AUTO_TARGET`, `AUTO_STATE`, `AUTO_MENTION_UNVERIFIED`, `POST_UNKNOWN`, `CANCELLED`, `AUTO_EXPIRED`) still stop the session immediately.
- Tested the quality gate: below-threshold scores produce a record with no draft and no publication, an unscorable answer fails closed, and the threshold can keep posting while omitting the owner mention.
- Tested the daily owner-mention limit, the daily analysis limit, and that an always-on session ignores the session duration but still honours the stop switch and ends on queue exhaustion.
- Tested that the scoring rubric is application-owned: a hostile local system prompt never enters the scoring messages, and evidence is delivered as `untrusted_scoring_evidence`.
- Tested score parsing accepts only a plain integer 1-10 object (and an optional JSON fence) and rejects floats, booleans, out-of-range values, free text and oversized output.
- Auto scheduling/publication tests use a virtual clock and fake platform/provider responses; they are not live Bilibili submissions.

## v1.3 request-trace checks

- Tested that every outbound request is written as `requests/NNN-<purpose>.json` containing the exact assembled `messages`, and that `purpose` distinguishes `analysis`, `analysis-frames`, `score` and `draft`.
- Tested that image payloads are replaced by a size marker so a trace stays small, and that known secrets, cookies and signed URLs are redacted while the JSON remains structurally valid.
- Tested that trace writes are bounded to 200 entries per run, and that only the most recent 40 run folders keep their trace directories.
- Tested that the Auto outcome column reports owner mentions, unverified mentions, skipped mentions, scores and error codes instead of only a status string.
- Verified by replay against a stored `evidence.json` that the trace renders the real assembly (`system` capability boundary + local policy + task constraints, then `LOCAL USER TASK`, then `untrusted_video_evidence` with frame markers).

## v1.4 comment-voice and mention-only checks

- Diagnosed report-like comments from the stored request: the comment task was reusing the analysis capability boundary, whose clause 4 requires timestamps and coverage disclosures.
- Tested that the comment prompt no longer carries the timestamp/coverage duties while the analysis prompt still does, and that the comment task states the owner-report policy applies to analysis only.
- Tested that the comment reference material has headings, emphasis and standalone timestamps stripped without mangling the prose.
- Tested mention-only mode: no draft call is made at all, the submission body is empty with only the mention prefix, the cooldown suppresses further mentions, and the quality gate still applies.
- Tested that an empty comment body is accepted only when a mention is attached, and still rejected for `COMMENT_EMPTY` otherwise.

## Blocked or not performed

- **Real Chromium execution**: the host's isolated runtime does not expose `/proc/self/exe` to Chromium. The actual browser test reached the launch attempt and failed in native Chromium before a page could open. This is recorded as an environment skip, not a passing browser test. Browser seeking, session behavior and live selectors therefore remain unverified in a real Windows browser.
- **System-level file trace**: strace was attempted, but the host rejected `ptrace`. No claim is made that all native/child-process writes were traced. Windows Process Monitor verification remains outstanding.
- **Desktop GUI visual validation**: no usable graphical session was available. Tkinter source and layout were reviewed; a rendered interactive UI was not visually verified.
- **Windows execution**: no Windows machine was available. `install.bat`, DPAPI persistence, native Windows library loading, browser sandbox behavior, dialog layout and shutdown have not been exercised on Windows.
- **Live account / model provider**: no user API credential or signed-in Bilibili account was used. Real model network responses, gated subtitles, live recommendation/search discovery, unattended platform publication, notification delivery and public moderation visibility were not tested. Provider calls and comment request semantics were exercised using test doubles; actual local video decode and ASR used their real native engines.

This is a source delivery with the above verified components and explicit integration limitations, not a claim of end-to-end Windows production validation.

## Reproduce

On Windows after installation:

```bat
.venv\Scripts\python.exe -I -B main.py --test
.venv\Scripts\python.exe -I -B main.py --doctor
```

To verify real application writes, use Windows Process Monitor with filters for the project Python process, its embedded Node child, and this project's Chromium process tree. Check file-create/write/rename events, excluding OS-managed platform files separately. The Runtime report lists the intended paths. Do not include API keys, Cookies, or personal browser data in shared traces.

建议先在 Windows 本机用一个短视频进行登录、字幕、抽帧、分析和手动评论验收。诊断报告仅证明配置路径，不等同于原生进程完整文件追踪。
