# BiliScope

> A Bilibili video AI assistant — subtitle/frame understanding, timestamped Q&A, comment drafting & publishing, unattended Auto that watches recommendations and mentions the owner. Local Whisper transcription, OpenAI-compatible API, Patchright standalone browser. CN / EN bilingual UI.

[Auto · prompts · API guide](docs/AUTO_AND_PROMPTS.md) · [中文](README.md) · [Runtime policy](docs/RUNTIME_POLICY.md) · [Sources & licenses](THIRD_PARTY_NOTICES.md) · [Validation](docs/VALIDATION.md)

## Quick start

1. Install **CPython 3.12+** (64-bit, with Tcl/Tk; 3.13 / 3.14 also supported)
2. Extract to a writable folder, run `install.bat` — creates `.venv`, installs SHA-256-verified dependencies, downloads official Chromium
3. Run `launch.bat`, enter your API key in Settings (DeepSeek by default; any OpenAI-compatible endpoint works)
4. Sign in to Bilibili, enter a BV ID or video URL, click **Analyze video**

The ZIP ships source and manifests only — no preinstalled browser, venv, or model. Pins are in `requirements.lock`, `docs/browser-lock.json`, and `docs/model-lock.json`.

## Features

- **Video analysis** — Prefers timestamped subtitles; falls back to local Whisper base ASR (CPU, ~160 MB first download). Vision models receive sampled frames and may request specific moments. Defaults to first 30 min (configurable 1–120). Refuses to infer from title alone.
- **Auto** — Recommendations/search/queue sources, quality-gate scoring, owner UID auto-mention, optional unattended publishing. Recoverable failures back off and retry. Restart never auto-resumes.
- **System prompts** — Five presets (strict anti-injection / learning notes / owner update / concise / critical) + custom. Editable after loading.
- **Comments & mentions** — Draft generation, preview & send, UID-based @ (max 5, duplicates rejected). Login and names rechecked before submission. No duplicate content, 15-second minimum interval.
- **Privacy** — Key memory-only by default, optional DPAPI encryption. All files inside project dir. No system env/registry changes. No telemetry.

## Security boundaries

- Subtitles, comments, and images enter only as untrusted evidence — never in system/developer messages
- Model has only bounded frame capture — no file / shell / network / config / publish tools
- Auto-mention target comes only from user-entered UID — never extracted from content
- Publication gate checks injection patterns, credential patterns, and known secrets; unknown outcomes are never retried
- Scoring rubric is application-owned and cannot be overridden by prompts

See [Auto, prompts & API guide](docs/AUTO_AND_PROMPTS.md).

## Layout

| Path | Contents |
| --- | --- |
| `biliscope/` | Application source (19 modules) |
| `docs/` | Docs, dependency sources & licenses |
| `tests/` | Unit / integration / UI tests |
| `runtime/` | Runtime data (logs/cache/models/config) — not tracked |
| `.venv/` | Python dependencies — generated on install, not tracked |

## Tests

```bat
.venv\Scripts\python.exe -I -B main.py --test
```

43 tests, 42 passed, 1 skipped. See [VALIDATION.md](docs/VALIDATION.md).

## Troubleshooting

`doctor.bat` generates a diagnostics report (paths only, no keys/cookies) · Logs in `runtime/logs/` · TLS verification always on

## License

MIT. Dependencies, browser, codecs, and model weights retain their individual licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
