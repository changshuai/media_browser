# 多媒体知识库系统

基于大模型的本地多媒体资源管理系统，支持图片和视频的智能描述与检索。

## 功能特点

- 图片管理
  - 自动生成图片描述
  - 基于描述的智能检索
  - 支持批量导入和处理

- 视频管理
  - 自动提取关键帧
  - 生成视频整体描述
  - 关键帧场景描述
  - 智能视频检索

## 安装要求

- Python 3.8+
- OpenCV
- PyTorch
- Transformers
- 其他依赖见 requirements.txt

## 安装步骤

1. 克隆仓库
```bash
git clone [repository-url]
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 运行系统
```bash
python main.py
```

## 使用说明

1. 图片处理
   - 将图片放入 `data/images` 目录
   - 运行图片处理脚本 `python process_images.py`

2. 视频处理
   - 将视频放入 `data/videos` 目录
   - 运行视频处理脚本 `python process_videos.py`

3. 检索
   - 使用 `search.py` 进行内容检索 