# A10 进阶产品化验收记录

日期：2026-10-04
验收结论：`PASS_WITH_BOUNDED_LIMITATIONS`
验收基线：`feature/h3-advanced-workflows`，`920d7e63e45c74c25379da849ff45a7f93ae6985`

## 范围与方法

本阶段把已完成的 A5–A9 能力、Job/Result 生命周期、交付、恢复和导出入口作为一个产品链路验收。优先复用既有 Job/Result；不创建 Job，不提交 Comfy `/prompt`，不运行 H3/GPU，也不改变历史结果、Golden 工作流或模型。能力不兼容时必须明确拒绝，不能静默降级。

该证据由已验收阶段的真实执行记录、当前源代码/集成回归和只读 Studio 状态共同组成；不是声称存在一个同时启用所有高级控制的单一 H3 执行。需要组合但尚未验证的能力仍维持 fail-closed。

## 产品链路证据

| 产品环节 | 证据与结论 |
|---|---|
| Project / Study 与已批准参考 | A5/A6 沿用同一审批与来源身份架构；独立的 A5 guide 与 A6 reference-role Study preflight 集成测试通过。 |
| 质量档位与真实生成 | A4.2 的 NATIVE_HIGH 有受控 GPU 证据；STANDARD 仍是候选而非 READY。不得把候选能力显示成已就绪。 |
| Storyboard / 多参考 | A5 已有多 guide 原生执行和结果链路；A6 已有图像角色 Ref2VA 的真实执行与结果证据。 |
| Director / Timeline / Retake | A7 既有 shot、retake 与 lineage 均已记录；摄影意图只作为生成指令，不宣称确定性 3D 相机路径。 |
| Result / 诊断 / 恢复 | Job 详情具备运行时身份、执行 SHA 和阶段信息；“恢复已有结果”明确说明不会重新生成。恢复实现由强身份、运行时路由和幂等回归覆盖。 |
| Delivery / 长片队列 | A8 的四类 CPU 交付副本和探测记录、A9 的五镜头队列与组装结果均使用既有产物；未把后处理描述成 H3 原生细节提升。 |
| 预览 / 导出 | Output Review 提供原生视频下载、交付视频下载和媒体预览；当前源文件与已安装 Studio 的相关前后端文件指纹一致。 |

只读运行确认：Studio `/api/health` 为健康；生产 Comfy 队列为 0 running / 0 pending。既有完成结果的 Studio 媒体路径已验证 `HTTP 206 Partial Content`。本次没有触发下载副本或修改任何 Job。

## 能力边界与已知限制

- A5：第二 guide 的精确切换时间响应较弱，转换表现为剪辑式切换；不宣称连续相机运动或确定性切点。
- A6：当前验收范围为图像参考角色；视频/音频 ingest 尚不可用。Ref2VA 与 AddGuide 同一执行的组合尚未验证，预检必须拒绝，不得伪装成功。
- A7：`camera_intent` 不是相机 XYZ/6DoF API；镜头差异化在现有样本中有限。
- A8：交付由 CPU FFmpeg 后处理产生；画布适配可能加边，不代表更高原生生成细节。
- A9：历史组装记录缺少可解码帧数证据；报告不补造帧数。
- 本记录关闭的是 G / A10 产品化阶段，不替代 Final C/D/E/F。尤其 UX 截图与键盘/DPI 审核、可靠性 soak/低盘模拟、全套安装升级卸载验收仍须在 Final Closeout 单独完成。

## 验证与安全

- 本轮聚焦 A10 跨阶段预检：`1 passed`。
- 本轮 A5 恢复、A8 交付、A9 长片聚焦回归：`57 passed`。
- CPU 全回归：`1029 tests`，`4 skipped`，`0 failed`（96.482 秒）。
- Regression inventory：`--check` 通过；测试数及既定 skip 基线未变化。
- `git diff --check`：通过。
- 运行时安全：生产 Studio 健康，生产 Comfy 队列为空；实验端口保持离线；无新 Job、无 `/prompt`、无 GPU 执行。
- 隐私：此记录不含 Prompt 文本、参考/生成媒体、私有绝对路径、凭据、token 或原始运行时日志。现有仅本机工具与素材保持未跟踪。
- 资源：回归结束后未发现 pytest/unittest/FFmpeg/AGY 常驻进程；D 盘可用空间约 115 GiB，本项目临时会话缓存此前盘点约 50 MiB，未清理用户数据。
- 独立外部 Review：`UNAVAILABLE`。Observer 在 AGY 启动前因 Windows 执行器的 `NUL` 路径错误失败；不代表 Review 通过，也不引用外部意见。临时审查 worktree 已清理。

## 阶段决策

A10：`COMPLETE_WITH_BOUNDED_LIMITATIONS`。现有真实 Job/Result、界面能力、恢复/交付链路和跨阶段回归足以证明高级能力已进入 Studio 产品路径；限制已明确展示或 fail-closed，未发现需要伪装成 READY 的不兼容项。

按主方案，G 进阶产品层达到 `100%`，贡献 `10.00%`；此时全产品路线图为 `95.80%`，**不是整体完成**。Final C、D、E、F 仍须逐项通过后，才能计算最终百分比。

下一阶段：Final Product Closeout，先完成 Final C Prompt Intelligence 的剩余契约核查与回归。
