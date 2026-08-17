# PATCH2.8-G — Public Release File List

最终 GitHub 公开仓库应包含：

## Directories

```
launcher/        production launcher（env check / process / lock / logger / bat）
apps/            architect_video_studio（UI + mock API + state machine）
runtime/         contracts / adapters / prompt bridge / validation
workflows/       01-05 native workflow JSON（只读）
configs/         baseline / schema / profiles / catalog
references/      known_good_h3（公开上游 Skill 参考）
samples/         合成示例（01/05 + README）
docs/            公开文档集（User Guide / Developer Architecture / Workflow Spec /
                 Release Checklists / Policies / G 系列）
tests/           regression suite
```

## Documents（公开集）

- `README.md`
- `THIRD_PARTY_NOTICES.md`
- `docs/User_Guide.md`
- `docs/Developer_Architecture.md`
- `docs/Workflow_Spec/01..05`（5 份）
- `docs/PATCH2.8D_RELEASE_CHECKLIST.md`
- `docs/PATCH2.8E_RC_CHECKLIST.md`
- `docs/PATCH2.8F_Public_Data_Policy.md`
- `docs/PATCH2.8F_Final_RC_Gate.md`
- `docs/PATCH2.8G_Documentation_Map.md`
- `docs/PATCH2.8G_Public_Release_File_List.md`
- `docs/PATCH2.8G_Final_Report.md`

## Samples / Workflows / Licenses

- `samples/01_Exterior_Hero.png`、`samples/05_Slow_Walkthrough.png`（合成）
- `workflows/*_NATIVE.json`（5 份）
- `THIRD_PARTY_NOTICES.md`（License 声明）

## 确认不包含

- ❌ userdata / logs / outputs / runtime.lock / env_report.json
- ❌ models（权重 / `*.safetensors`）
- ❌ `docs/internal_archive/`（内部开发归档，.gitignore 排除）
- ❌ distribution_test / install_test（分发验证工作区）
- ❌ 私有图片 / 客户项目 / 机器绝对路径 / 密钥

## Git 卫生复核

```
git ls-files（禁止项）：仅 userdata/README.md（文档占位，非运行时数据）
check-ignore：models/*.safetensors、userdata、logs、runtime.lock、.env、
              docs/internal_archive/ 全部 IGNORED
```
