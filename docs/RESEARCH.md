# Research and implementation decisions

Research date: 2026-10-22. Stars were point-in-time observations, not proof of recent growth.

| Reference | Observation | Decision |
| --- | --- | --- |
| https://github.com/CZX2244/dsh-bilibili | Transcript/comments/danmaku, semantic frame selection, local/cloud ASR options | Use transcript-first analysis plus targeted frames; implement independently in Python |
| https://github.com/moxingovo/dsh-bilibili | Read-only retrieval and actual frame blocks | Separate text-only and image-capable model paths |
| https://github.com/xiaoyaya191/bilibili_learning_bot | Video browsing, comments, mention-triggered interactions | Keep this first version focused on one user-selected video and explicit manual publication |
| https://github.com/ilps2/dsvu-videounderstanding | Information layer from ASR and visual evidence | Preserve timestamps and evidence provenance; avoid undocumented quality claims |
| https://api-docs.deepseek.com/guides/vision/ | Flash supports image inputs | Default to `deepseek-flash`; make model modality explicit |
| https://api-docs.deepseek.com/quick_start/pricing/ | Pro lacks vision in current capability table | Text-only route remains available |
| https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python | Python API uses an embedded driver and a Chromium-family browser | Include Node and native libraries in the provenance model |
| https://www.chromium.org/getting-involved/download-chromium/ | Chromium snapshots and Chrome for Testing are distinct distributions | Install official unbranded Chromium snapshots, pinned to REVISIONS and archive SHA-256 |
| https://github.com/k2-fsa/sherpa-onnx | Local CPU recognition with open-source ONNX runtime | Use Whisper ONNX via sherpa-onnx, without CUDA or vendor inference SDKs |
| https://github.com/pskdje/bilibili-API-collect/blob/main/docs/misc/sign/wbi.md | Web request signing and known protocol vectors | Test against published reference vector; use percent encoding for spaces |

Application code is original. The Bilibili Web API access is unofficial, session-scoped and may need changes when platform behavior changes. No Harness or MCP package is installed. Video comments are Web submissions through the current Patchright session, rather than a second exported Cookie client.

## v1.1 implementation references

- OpenAI Chat Completions schema: https://developers.openai.com/api/reference/python/resources/chat/subresources/completions
- Separation of untrusted evidence and instructions: https://developers.openai.com/api/docs/guides/agent-builder-safety

Auto is implemented locally with bounded sessions and persistent publication reservations. It does not install an agent harness or external scheduler. Prompt presets are original application policy examples; they do not replace code-enforced destination and permission controls.
