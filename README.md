# MP4 Blur Editor / MP4 视频区域模糊编辑器

## Motivation / 制作初衷

**中文**  
我做这个工具，是因为常用的视频水印消除软件里：有些效果很差，有些又需要本地很强的显卡和显存。  
这个项目提供一个极简方案：效果不追求“完美去除”，但胜在**上手难度低、效果稳定、对硬件要求低**。

**English**  
This tool was built because many watermark-removal tools either produce poor results or require powerful local GPUs and large VRAM.  
This project offers a minimal workflow: it does not aim for perfect object removal, but focuses on **low complexity, stable output, and low hardware requirements**.

---

## Features / 功能

- Import / export MP4 only（仅支持 MP4 输入输出）
- Draw multiple rectangles on preview（可绘制多个矩形区域）
- Per-region independent timeline（每个区域独立开始/结束时间）
- Effects:
  1. Gaussian Blur
  2. Mosaic
  3. Frosted Glass
- Project save/load as JSON（工程保存/加载为 JSON）
- Export uses FFmpeg at source resolution and fps（导出保持原分辨率与帧率）

---

## UI Overview / 界面布局

- Left: video preview + timeline（左侧预览与时间轴）
- Right: region list + properties（右侧矩形列表与属性面板）
- Hint in toolbar: hold left mouse button and drag to place rectangle（顶部提示：按住鼠标左键拖动可放置矩形）

---

## Quick Start / 快速开始

### 1) Install dependencies / 安装依赖

```bash
pip install -r requirements.txt
```

### 2) Launch / 启动

Windows:

- Double click `一键启动.bat`
- Stop with `一键停止.bat`

Or:

```bash
python main.py
```

---

## Basic Workflow / 基本操作

1. Import MP4（导入 MP4）
2. In preview, drag mouse to create rectangle（拖拽创建矩形）
3. Select region and edit properties on right panel（在右侧面板设置属性）
   - effect type
   - effect strength sliders（强度滑动条：左弱右强）
   - start/end time（可用“读入当前时间”按钮）
4. Play to preview effect（点击播放时才渲染效果预览）
5. Export MP4（默认输出名：`原视频名_blur.mp4`）

---

## FFmpeg Notes / FFmpeg 说明

The app resolves FFmpeg tools in this order:

1. `FFMPEG_BIN` + `FFPROBE_BIN` env vars
2. `mp4_blur_editor/ffmpeg/`
3. `../Propainter1.6/ffmpeg/`
4. system PATH

程序会按以上顺序自动寻找 ffmpeg / ffprobe。

---

## Project Structure / 项目结构

```text
mp4_blur_editor
├─ app
│  ├─ main_window.py
│  ├─ video_canvas.py
│  ├─ ffmpeg_exporter.py
│  ├─ models.py
│  └─ project_io.py
├─ main.py
├─ requirements.txt
├─ 一键启动.bat
└─ 一键停止.bat
```
## Tech Stack / 技术栈

- Python
- PySide6
- FFmpeg

## License / 许可证

This project is licensed under the MIT License.

本项目采用 MIT License 开源。

