# MiniMax H3 建筑师 RC3 本地工作流测试指南 (Architect RC3 Test Guide)

欢迎体验 MiniMax H3 建筑 AI 视频系统 V0.8.0-RC3！本版本已全面完成本地 ComfyUI 模型路径与真实生产工作流适配。

---

## 1. 一键双击启动本地 ComfyUI

双击根目录一键启动脚本：
```powershell
launcher/Start_MiniMax_H3_Architect.bat
```
系统将自动检查 CUDA 环境、模型路径并自动打开 ComfyUI 浏览器页面：`http://127.0.0.1:8188`。

---

## 2. 选择 5 大真实本地生产工作流

在 ComfyUI 界面中加载 `workflows/` 目录下的 5 大真实工作流之一：

1. **`01_Exterior_Hero.json`**：外观主透视展示动画（慢速推镜头）。
2. **`02_Day_Night_Transition.json`**：日落黄昏至夜景灯光渐变动画。
3. **`03_Material_Detail.json`**：清水混凝土与木百叶细部材质特写。
4. **`04_Drone_Aerial.json`**：高空无人机环绕总平面与场地上下文动画。
5. **`05_Slow_Walkthrough.json`**：人行视角中庭与室内空间漫游动画。

---

## 3. 上传效果图与输入设计需求

1. 在 `LoadImage` 节点上传 1~3 张建筑效果图（存入 `userdata/personal_workspace/input_images/`）。
2. 输入自然语言需求（例如：“生成建筑鸟瞰宣传视频，保持建筑体量，缓慢无人机环绕，黄昏光线”）。
3. 提示词转换模块将自动解析并生成符合 MiniMax H3 结构的镜头、运动、光影、几何与材质控制词。

---

## 4. 点击 Queue 导出 1280x720 高清视频

1. 点击 **Queue Prompt** 提交渲染。
2. 动画视频将自动生成并保存在：
   ```powershell
   userdata/personal_workspace/outputs/
   ```
