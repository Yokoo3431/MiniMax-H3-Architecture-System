# Third-Party Notices

本产品由以下第三方组件构成。请遵守各组件各自的许可条款。

## Project License

- 本项目源码以 **Apache License 2.0** 授权（见 `LICENSE`）
- 第三方组件许可见下表；**模型权重为独立授权**，不随本仓库分发，
  需单独获取并遵守上游（MiniMax H3、Qwen）条款

> 注：模型权重不随本仓库分发；用户需自行获取并遵守相应授权。本清单供
> 发布与合规审核使用（许可信息以各上游仓库当前声明为准）。

---

## 1. ComfyUI

| 项 | 值 |
| --- | --- |
| License | GPL-3.0 |
| Source | https://github.com/comfyanonymous/ComfyUI |
| Usage | 本地视频生成运行时（Native v0.33.1，冻结；本产品仅通过 HTTP 边界调用，不修改其源码） |

## 2. MiniMax H3（节点 / 技能 / 模型）

| 项 | 值 |
| --- | --- |
| License | 以上游 MiniMax-AI/MiniMax-H3 仓库声明为准（模型另有授权条款） |
| Source | https://github.com/MiniMax-AI/MiniMax-H3 |
| Usage | MiniMax H3 Native 节点（ComfyUI bundled）、h3-prompt-writing 技能（只读引用，版本 pin）、模型权重（用户自备） |

### 2.1 Production H3 support layer

| 项 | 值 |
| --- | --- |
| Package | `ComfyUI_RH_MinMaxH3` |
| License | Apache-2.0 (`LICENSE` in the pinned source) |
| Source | https://github.com/HM-RunningHub/ComfyUI_RH_MinMaxH3 |
| Immutable commit | `d6c5f7b0d4e03936ac4a9834be63ecc6b5637dad` |
| Install policy | Exact commit archive only; no `main`/`latest`/Manager dependency |
| Windows production delta | Project-audited PREAD-safe mmap/loader patch, recorded in `configs/support_layer_manifest.yaml` |

### 2.2 MiniMax H3 model configuration/support data

| 项 | 值 |
| --- | --- |
| License | MiniMax H3 Community License Agreement |
| Source | https://huggingface.co/MiniMaxAI/MiniMax-H3 |
| Immutable revision | `42ed227ee7df40d41602854ae760620d6eb651fe` |
| Scope | FL2VA non-weight configuration, tokenizer and processor files only |
| Install policy | Download from the immutable revision at install time; `*.safetensors` is rejected by the support-data installer |
| Distribution notice | `MiniMax H3 is licensed under the MiniMax H3 Community License Agreement, Copyright © 2026 MiniMax. All Rights Reserved.` |
| Compliance | Applicable Territory, Acceptable Use Policy and upstream downstream-notice obligations apply; users must review `LICENSE` before use |

## 3. Qwen / Qwen2.5-VL (Qwen3-VL 文本编码器)

| 项 | 值 |
| --- | --- |
| License | Apache-2.0（Qwen 开源模型系列，以官方声明为准） |
| Source | https://github.com/QwenLM/Qwen2.5-VL |
| Usage | 文本编码器（qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors）经 ComfyUI CLIPLoader 加载，用于 prompt 编码 |

## 4. Python 依赖（运行时使用）

| 包 | License（常见） | 用途 |
| --- | --- | --- |
| torch | BSD-3-Clause | GPU 张量/推理 |
| safetensors | Apache-2.0 | 模型权重加载（PREAD 后端） |
| opencv-python | Apache-2.0 | 参考图质量卡 |
| numpy | BSD-3-Clause | 图像/数值处理 |
| PyYAML | MIT | 契约/配置解析 |
| ffmpeg / ffprobe | LGPL/GPL（二进制分发需注意） | 视频探测/封装验证 |

## 5. VideoHelperSuite

| 项 | 值 |
| --- | --- |
| Package | `ComfyUI-VideoHelperSuite` |
| License | GPL-3.0-only (`LICENSE` in the pinned source) |
| Source | https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite |
| Immutable commit | `4ee72c065db22c9d96c2427954dc69e7b908444b` |
| Required registration | `VHS_VideoCombine` |
| FFmpeg strategy | `imageio-ffmpeg==0.6.0` bundled executable for VHS; no global PATH mutation |

The pinned H3 support layer documents that Ref2VA reference media additionally
expects `ffmpeg` and `ffprobe` on PATH. The current production machine has no
system `ffmpeg`/`ffprobe`; the five frozen I2VA/FL2VA workflows do not use that
optional Ref2VA path. A future distribution component must make that optional
requirement explicit rather than silently assuming a global binary.

## 6. 使用注意

- 若将本产品与 ComfyUI 一起分发，须遵守 GPL-3.0 相应义务（提供对应源码/许可）
- 模型权重、H3 模型与技能的分发需单独取得授权；本仓库不包含权重
- ffmpeg 二进制分发需按所选构建的许可（LGPL/GPL）履行义务

## 7. Shareable installer notice

`ArchitectVideoStudio-Setup.exe` is built with the Windows IExpress tool and
contains application source/configuration plus the first-run bootstrap script.
It does not contain ComfyUI Runtime binaries or model weights. The installer
downloads the pinned official ComfyUI portable archive and user-confirmed H3
assets over HTTPS, verifies the manifest checksums, and keeps the downloaded
weights outside the project source package.
