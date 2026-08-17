# PATCH2.8-G — Documentation Map

**Phase:** RC3.4 PATCH2.8-G — Release Documentation Sanitization
**Date:** 2026-08-17
**Status:** CLASSIFICATION DONE（143 份内部文档已归档，6 份公开 + 5 份 Workflow Spec）

---

## 1. Public（进入 GitHub）

| 文件 | Category | Decision |
| --- | --- | --- |
| `README.md`（仓库根） | Public | 保留（0 隐私命中） |
| `THIRD_PARTY_NOTICES.md`（仓库根） | Public | 保留（License） |
| `docs/User_Guide.md` | Public | 保留（5 步安装/教程） |
| `docs/Developer_Architecture.md` | Public | 保留（架构概览） |
| `docs/Workflow_Spec/01_Exterior_Hero.md` … `05_Slow_Walkthrough.md` | Public | 保留（5 份，0 隐私命中） |
| `docs/PATCH2.8D_RELEASE_CHECKLIST.md` | Public | 保留（Release Notes 类） |
| `docs/PATCH2.8E_RC_CHECKLIST.md` | Public | 保留 |
| `docs/PATCH2.8F_Public_Data_Policy.md` | Public | 保留（Public Policy） |
| `docs/PATCH2.8F_Final_RC_Gate.md` | Public | 保留 |
| `docs/PATCH2.8G_Documentation_Map.md` / `PATCH2.8G_Public_Release_File_List.md` / `PATCH2.8G_Final_Report.md` | Public | 新建 |

## 2. Internal（不进入 GitHub → `docs/internal_archive/`）

**143 份** 已移动至 `docs/internal_archive/`，包括：

- GPU debug / Windows crash / mmap·pread 调查（PATCH2.4-R1/R2/R3 等）
- 机器路径报告（PATCH2.8C Runtime/Install 报告等）
- 私有项目验证报告（W02/W03/W05、Golden Migration、QA 系列）
- 实验/阶段报告（V0.6.5 → V0.8.0-RC3.3 全部、PATCH2.1/2.2/2.3/2.6A/2.6C、
  RC3.3_*、diagnostic/migration/handoff 等）
- PATCH2.8D/E/F Final Report 与 Audit/Cleanup 报告（运维证据）

`docs/internal_archive/` 已加入 `.gitignore`：**保留本地历史，不进入公开发布**。

## 3. 判定规则

- 含真实项目名 / 客户名 / 机器绝对路径 / 用户目录 / 私有图片路径 / 内部账号 → Internal
- GPU 调试、崩溃分析、mmap/pread 调查、私有项目验证、实验报告 → Internal
- README / 用户指南 / 开发架构 / 架构概览 / License / 政策 / 发布清单 → Public

## 4. 结论

公开文档集与内部开发归档已明确隔离；公开文档 0 隐私命中，路径约定使用
`<PROJECT_ROOT>` / `<USER_HOME>` / `<SAMPLE_PROJECT>` 占位。
