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

## 3. Qwen3-VL（MiniMax H3 文本编码器）

| 项 | 值 |
| --- | --- |
| License | Qwen3-VL 上游代码/模型系列为 Apache-2.0；MiniMax H3 发布的具体编码器权重仍须按 MiniMax H3 Community License Agreement 使用，不由本产品重新授权 |
| Source | Qwen3-VL: https://github.com/QwenLM/Qwen3-VL；实际权重文件来自 MiniMax-H3 固定 revision `42ed227ee7df40d41602854ae760620d6eb651fe` |
| Usage | 文本编码器 `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` 经 ComfyUI CLIPLoader 加载。此权重不随产品包分发，由用户按安装器的许可确认流程从固定上游获取 |

MiniMax H3 官方许可文本说明其 encoder 使用 Qwen3-VL-32B，并将该 encoder
列为 Apache-2.0；同时，H3 权重及其输出仍受 MiniMax H3 Community License
Agreement 的适用范围和使用条件约束。两者不是同一许可，也不能用 Qwen
上游许可替代 H3 权重许可。固定下载 revision 与权重清单见
`models/manifest.json` 和 `configs/installation_manifest.yaml`。

## 4. Python 依赖（生产运行时）

下表列出当前生产 support-layer manifest 中明确 pin 的包。ComfyUI
portable archive 内的 PyTorch/CUDA 核心栈按该归档整体固定；其版本及随附
第三方 notices 应以安装时验证过的官方归档为准，不在此猜测独立 pip 版本。

| 包 | 固定版本 | License / 许可说明 | 用途 |
| --- | --- | --- | --- |
| `transformers` | `5.8.1` | Apache-2.0 | H3 文本编码器运行支持 |
| `tokenizers` | `0.22.2` | Apache-2.0 | tokenizer 支持 |
| `accelerate` | `1.14.0` | Apache-2.0 | H3 模型加载支持 |
| `safetensors` | `0.8.0` | Apache-2.0 | 安全张量/权重加载 |
| `numpy` | `2.4.6` | BSD-3-Clause | 数值处理 |
| `sentencepiece` | `0.2.1` | Apache-2.0 | tokenizer 支持 |
| `einops` | `0.8.2` | MIT | 张量维度操作 |
| `Pillow` | `12.2.0` | MIT-CMU | 图像处理 |
| `opencv-python` | `5.0.0.93` | wrapper 为 MIT；OpenCV 为 Apache-2.0；官方 wheel 内 FFmpeg 为 LGPL-2.1，其他二进制依赖见其 notices | 参考图处理 |
| `imageio-ffmpeg` | `0.6.0` | Python package 为 BSD-2-Clause；捆绑 FFmpeg 二进制的许可取决于具体构建 | VHS 的隔离 FFmpeg 可执行文件 |
| `comfy-kitchen` | `0.2.16` | Apache-2.0 | ComfyUI 原生 H3 支持层依赖 |

版本来源：`configs/support_layer_manifest.yaml`。上游许可证声明参考：
[transformers](https://github.com/huggingface/transformers/blob/main/LICENSE)、
[tokenizers](https://github.com/huggingface/tokenizers)、
[accelerate](https://github.com/huggingface/accelerate/blob/main/LICENSE)、
[safetensors](https://github.com/safetensors/safetensors/blob/main/LICENSE)、
[NumPy](https://github.com/numpy/numpy/blob/main/LICENSE.txt)、
[SentencePiece](https://github.com/google/sentencepiece/blob/master/LICENSE)、
[einops](https://github.com/arogozhnikov/einops/blob/main/LICENSE)、
[Pillow](https://github.com/python-pillow/Pillow/blob/main/LICENSE)、
[opencv-python 与 wheel notices](https://github.com/opencv/opencv-python#licensing)、
[imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg/blob/main/LICENSE)、
[comfy-kitchen](https://github.com/Comfy-Org/comfy-kitchen/blob/main/LICENSE)。
以上为上游项目声明页，不是本产品的法律意见；具体分发仍须随实际 pinned
artifact 核验其附带 notices。该清单不代表第三方许可证已由本项目重新授权。

`torch`、`torchvision`、`torchaudio`、CUDA runtime 与 ComfyUI core 属于冻结的
portable runtime；安装器按官方 ComfyUI 归档 SHA-256 校验，不单独升级或替换。
`PyYAML` 不属于上述 production support-layer manifest 的显式 pin，故不在此
列为产品固定版本。

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

## 6. Shoelace and Tabler Icons (Architect Video Studio frontend)

| Component | License | Source / revision | Included files |
| --- | --- | --- | --- |
| Shoelace | MIT | https://github.com/shoelace-style/shoelace, v2.20.1 (`fb59fda70ed737c92611051b49bc7e3a5fed5dc5`) | `apps/architect_video_studio/frontend/vendor/shoelace/shoelace.js`, `dark.css`, `chunks/`, `internal/` |
| Tabler Icons | MIT | https://github.com/tabler/tabler-icons | Selected navigation/action SVGs under `apps/architect_video_studio/frontend/vendor/tabler/` |

These frontend assets are vendored for local/offline desktop use. AVS uses the
components only as presentation primitives; they do not own Study, Job,
engine, provider, or generation state.

The vendored Tabler selection has no verified upstream release/commit identifier
in the repository history. To make the shipped bytes auditable without inventing
an upstream pin, the current local files are identified by SHA-256:

| File | SHA-256 |
| --- | --- |
| `briefcase.svg` | `FFE1DBC475B4B75D3AFDF2B42CBD672816CEFF6658E5B6E52987DDA21D57720B` |
| `copy.svg` | `AAA6BAEC777F05DFCBB72F8B59931E70E129CAAF3B0AF4648DB26E4A236B7B14` |
| `dots.svg` | `B59959AF13CDEB1E633636AF444EEDC4D812B8CABFBCA4A18681E5DCD415C1B6` |
| `file-description.svg` | `54FB97979D8FBC94D28E7EEF6A3E9A694B2433C728616FC541FD7C4A1DB3F867` |
| `home.svg` | `54176A0A2409D90B00CCBFDEE27339E7A58C8169E895870C4E486962B38C1111` |
| `photo.svg` | `8ADEDF6F2C24C68ABFC109260ED8AE5C6B45F09DFB5A4B68DBBA2305D7B8D6FB` |
| `player-play.svg` | `99974097AE153BEA9D2802B5DDBCA914B01475382B180245EE26C61DE4E58579` |
| `plus.svg` | `B87F14E060FD74BC2B008D609063F35BF4DE523AAFA17C06FDCC300F99775EE8` |
| `refresh.svg` | `A7E271B87F67044F879939281AEE9E9B1157880AF06080F75FE7A1D3FC6D93C8` |
| `settings.svg` | `FE17A5A8B646678A39EC9D8969C10B37EC75F43F75DA541DB906CC54A49FA1C6` |
| `trash.svg` | `3622D02D66EFE5CF7BCABC48D4F0643781887055681344DB003FAC9127DE0896` |
| `LICENSE` | `DBFA6CFF2E8426878267C6719FF68DCD8BC3DADAFFB2207F5C46CE939C4BECD3` |
## 6.1 Adobe Spectrum CSS

| Component | License | Source / version | Included files |
| --- | --- | --- | --- |
| Adobe Spectrum CSS | Apache-2.0 | https://github.com/adobe/spectrum-css, v2.13.0 (`2e3a674c4e302219f36774745d94f3fccb22c692`) | `apps/architect_video_studio/frontend/vendor/spectrum/spectrum-dark.css`, `LICENSE` |

The Study page uses the locally packaged Spectrum dark stylesheet as its component/token reference. No Adobe branding or Spectrum source repository is bundled.

## 7. 使用注意

- 若将本产品与 ComfyUI 一起分发，须遵守 GPL-3.0 相应义务（提供对应源码/许可）
- 模型权重、H3 模型与技能的分发需单独取得授权；本仓库不包含权重
- ffmpeg 二进制分发需按所选构建的许可（LGPL/GPL）履行义务

## 8. Shareable installer notice

`ArchitectVideoStudio-Setup.exe` is built with the Windows IExpress tool and
contains application source/configuration plus the first-run bootstrap script.
It does not contain ComfyUI Runtime binaries or model weights. The installer
downloads the pinned official ComfyUI portable archive and user-confirmed H3
assets over HTTPS, verifies the manifest checksums, and keeps the downloaded
weights outside the project source package.
