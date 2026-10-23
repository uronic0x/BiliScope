# Third-party components and source traceability

This ZIP distributes original Python source, dependency locks, source inventories, and license notices. It does not contain executable browser/driver/library binaries or ASR model weights. The installer fetches fixed upstream artifacts using HTTPS and verifies pinned SHA-256. No unknown executable is copied from an unofficial binary bundle.

## Components

| Component | Pinned version | Source / notices |
| --- | --- | --- |
| Application code | 1.1.0 | This source tree; MIT |
| Patchright Python | 1.64.2 | [Python source](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python), [patched JS driver source](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright); Apache-2.0 and bundled notices |
| Embedded Node | Version read from the installed driver | [Node source](https://github.com/nodejs/node); upstream [license and bundled third-party notices](https://github.com/nodejs/node/blob/main/LICENSE) |
| pyee | 14.0.0 | [Source](https://github.com/jfhbrook/pyee); MIT |
| greenlet | 3.5.6 | [Source](https://github.com/python-greenlet/greenlet); MIT / Python-2.0 |
| typing-extensions | 4.15.0 | [Source](https://github.com/python/typing_extensions); PSF-2.0 |
| NumPy | 2.5.4 | [Source](https://github.com/numpy/numpy); BSD-3-Clause plus bundled notices; includes [OpenBLAS](https://github.com/OpenMathLib/OpenBLAS) and a Windows C++ runtime component traceable to [Microsoft STL](https://github.com/microsoft/STL) |
| PyAV | 19.0.2 | [Source](https://github.com/PyAV-Org/PyAV), [FFmpeg wheel build source](https://github.com/PyAV-Org/pyav-ffmpeg); Python wrapper BSD-3-Clause; bundled media libraries have separate LGPL/GPL and codec licenses |
| PySide6 / PySide6-Essentials / PySide6-Addons / shiboken6 | 6.11.1 | [Qt for Python source](https://code.qt.io/cgit/pyside/pyside-setup.git); LGPL-3.0 / GPL-2.0 / GPL-3.0 (used as dynamically linked Qt libraries; relinking/replacement stays possible via the unlocked `requirements.lock` workflow) |
| sherpa-onnx | 1.13.8 | [Versioned source](https://github.com/k2-fsa/sherpa-onnx/tree/v1.13.8); Apache-2.0 |
| sherpa-onnx-core | 1.13.8 | Same versioned repository and its build configuration; includes [ONNX Runtime](https://github.com/microsoft/onnxruntime) and [kaldi-native-fbank](https://github.com/csukuangfj/kaldi-native-fbank) |
| Official Chromium | Windows snapshot 1725026; Linux developer snapshot 1725108 | Exact upstream source commits, dependency REVISIONS, archive URLs and SHA-256 in [browser-lock.json](docs/browser-lock.json) |
| Whisper base multilingual ONNX | Revision `bb53ee204431c90d314c1cc08d28d23e5b7927cc` | [Converted artifacts](https://huggingface.co/csukuangfj/sherpa-onnx-whisper-base/tree/bb53ee204431c90d314c1cc08d28d23e5b7927cc), [conversion source](https://github.com/k2-fsa/sherpa-onnx/tree/v1.13.8/scripts/whisper), [original Whisper source and model license](https://github.com/openai/whisper); MIT |
| CPython / Tcl / Tk | User-provided CPython 3.12–3.14 | [CPython](https://github.com/python/cpython), [Tcl](https://github.com/tcltk/tcl), [Tk](https://github.com/tcltk/tk); platform prerequisites |

The program uses Windows APIs (including optional DPAPI) supplied by the user's operating system. Windows and its existing system runtime DLLs are platform prerequisites, not described as open-source application dependencies. The source inventory distinguishes upstream package code from compiler/platform runtime components. Source traceability does not establish a bit-for-bit reproducible compiler build.

## Media libraries

The checked Windows PyAV wheel includes FFmpeg, dav1d, libiconv, Opus, libwebp/libsharpyuv, SVT-AV1, libvmaf, libvpl, libvpx, x264, x265, zlib, GCC/libstdc++ runtimes and mingw-w64 winpthreads. These are open-source projects with their own licenses. The per-DLL source mapping and hash are in [source-manifest.json](docs/source-manifest.json). In particular, the FFmpeg build includes GPL codecs: the PyAV Python wrapper's BSD license must not be presented as the license of its entire binary distribution.

Primary sources: [FFmpeg](https://github.com/FFmpeg/FFmpeg), [dav1d](https://code.videolan.org/videolan/dav1d), [libiconv](https://www.gnu.org/software/libiconv/), [Opus](https://github.com/xiph/opus), [libwebp](https://chromium.googlesource.com/webm/libwebp/), [SVT-AV1](https://gitlab.com/AOMediaCodec/SVT-AV1), [libvmaf](https://github.com/Netflix/vmaf), [libvpl](https://github.com/intel/libvpl), [libvpx](https://chromium.googlesource.com/webm/libvpx/), [x264](https://code.videolan.org/videolan/x264), [x265](https://bitbucket.org/multicoreware/x265_git/), [zlib](https://github.com/madler/zlib), [GCC](https://gcc.gnu.org/git.html), [mingw-w64](https://github.com/mingw-w64/mingw-w64).

## Audit artifacts

- `requirements.lock`: exact package versions and wheel SHA-256 allowlist. Installation refuses sdists and undeclared dependencies.
- `docs/source-manifest.json`: checked Windows wheel hashes, every contained `.exe` / `.dll` / `.pyd` hash and source-project mapping.
- `docs/windows-wheel-audit.json`: original wheel binary and license file listings.
- `docs/licenses/`: upstream license/notice files extracted from the checked Windows wheels. Filenames are numbered to avoid name collisions.
- `docs/browser-lock.json`: official Chromium source commit and third-party REVISIONS as supplied alongside the upstream archive.
- `docs/model-lock.json`: fixed model revision, sizes and SHA-256 for every downloaded model file.
- After installation, `runtime/provenance/`: actual installed versions and native file hashes, Node version, exact browser provenance, upstream driver manifests and pip download receipts.

The inventory is a traceability record. It is not a full static-link source audit, independent binary attestation, or a promise that each artifact can be rebuilt byte-for-byte with an arbitrary compiler. No third-party compiled artifact is redistributed inside the source ZIP.

## 中文说明

压缩包仅含源码、固定版本和哈希清单、来源记录及许可证文本。安装器从上游下载原生组件，并验证固定 SHA-256。官方 Chromium 下载项明确区别于 Chrome for Testing；对应源码提交已记录。本地 ASR 使用 CPU 路径，不安装 CUDA、cuDNN、MKL 推理栈或来源不明的独立 EXE。

Windows 本身和已有系统运行库属于平台前置条件；本清单不把 Windows 系统组件称为开源。源码可追溯、哈希可核验与“可逐字节复现编译”是不同保证，后者未验证。各依赖的许可条款以其上游通知为准。
