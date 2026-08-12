# MiniMax H3 建筑师快速上手指南 (Architect Quick Start Guide)

欢迎使用 MiniMax H3 建筑 AI 视频系统 V0.8.0-RC2！本指南专为非程序员建筑师与设计师编写，无需任何代码修改与节点调试。

---

## 1. 1-Click 双击启动系统

1. 双击运行系统根目录下的启动脚本：
   ```powershell
   launcher/Start_MiniMax_H3_Architect.bat
   ```
2. 系统将自动自检 GPU 环境、初始化个人工作空间并启动 ComfyUI。
3. 浏览器将自动打开 ComfyUI 页面：`http://127.0.0.1:8188`。

---

## 2. 选择 5 大冻结建筑视频工作流

在 `workflows/` 目录下选择适合您设计目标的冻结工作流 JSON：

1. **`01_Exterior_Hero.json`**：建筑外观主透视展示动画（慢速推进全景）。
2. **`02_Day_Night_Transition.json`**：日落黄昏至夜景灯光渐变动画。
3. **`03_Material_Detail.json`**：清水混凝土、木百叶与玻璃细部材质特写。
4. **`04_Drone_Aerial.json`**：高空无人机环绕总平面与场地上下文动画。
5. **`05_Slow_Walkthrough.json`**：人行视角中庭与室内空间漫游动画。

---

## 3. 上传效果图与输入设计意图

1. 在 ComfyUI 界面中点击 `LoadImage` 节点，上传 1~3 张建筑效果图（文件自动保存在 `userdata/personal_workspace/input_images/`）。
2. 输入自然语言设计意图（例如：“制作黄昏时刻安藤混凝土美术馆慢速推进动画”）。
3. Prompt 桥接适配器将自动生成符合 MiniMax H3 官方格式的结构化 Prompt（镜头、运动、光影、几何保护、材质保留）。

---

## 4. 提交生成与获取视频

1. 点击 ComfyUI 界面右侧的 **Queue Prompt** 按钮。
2. 生成的 1280x720 24fps 高清动画视频将自动保存在：
   ```powershell
   userdata/personal_workspace/outputs/
   ```
