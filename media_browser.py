# -*- coding: utf-8 -*-
# media_browser.py version: 1.0

import sys, os, hashlib, tempfile, threading
from PyQt5.QtWidgets import (QApplication, QMainWindow, QFileDialog, QListWidget, QListWidgetItem, QLabel, QVBoxLayout, QWidget, QPushButton, QHBoxLayout, QAbstractItemView)
from PyQt5.QtGui import QPixmap, QIcon, QMovie
from PyQt5.QtCore import Qt, QSize, QEvent, QThread, pyqtSignal
from PIL import Image
import cv2
import imageio
import subprocess
import logging

THUMB_SIZE = (256, 256)
CACHE_DIR = os.path.join(tempfile.gettempdir(), 'media_browser_thumbs')
os.makedirs(CACHE_DIR, exist_ok=True)

IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif')
VIDEO_EXTS = ('.mp4', '.avi', '.mov', '.mkv', '.webm')

# 设置日志格式
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')

# 缩略图缓存路径
def thumb_cache_path(filepath, ext):
    h = hashlib.md5(filepath.encode('utf-8')).hexdigest()
    return os.path.join(CACHE_DIR, f'{h}{ext}')

# 新增：动态缩放函数
def get_scaled_size(orig_w, orig_h, max_size=256):
    if orig_w <= max_size and orig_h <= max_size:
        return orig_w, orig_h
    if orig_w > orig_h:
        scale = max_size / orig_w
    else:
        scale = max_size / orig_h
    return max(1, int(orig_w * scale)), max(1, int(orig_h * scale))

def generate_image_thumbnail(image_path, max_size=256):
    thumb_path = thumb_cache_path(image_path, '.png')
    logging.info(f"[Image] 缓存目录: {CACHE_DIR}")
    logging.info(f"[Image] 处理文件: {image_path}")
    logging.info(f"[Image] 缓存文件: {thumb_path}")
    if os.path.exists(thumb_path):
        try:
            with Image.open(thumb_path) as img:
                logging.info(f"[Image] 命中缓存，直接返回: {thumb_path}")
                return thumb_path, img.size
        except Exception:
            logging.info(f"[Image] 缓存损坏，重新生成: {thumb_path}")
    try:
        img = Image.open(image_path)
        orig_w, orig_h = img.size
        thumb_w, thumb_h = get_scaled_size(orig_w, orig_h, max_size)
        img.thumbnail((thumb_w, thumb_h), Image.LANCZOS)
        # 生成白色背景，居中粘贴
        bg = Image.new('RGB', (thumb_w, thumb_h), (255, 255, 255))
        bg.paste(img, (0, 0))
        bg.save(thumb_path)
        logging.info(f"[Image] 生成新缓存: {thumb_path}")
        return thumb_path, (thumb_w, thumb_h)
    except Exception as e:
        logging.error(f"[Image] 生成缩略图失败: {e}")
        return None, (max_size, max_size)

def generate_video_gif(video_path, max_size=256, target_frames=32, fps=8):
    thumb_path = thumb_cache_path(video_path, '.gif')
    logging.info(f"[Video] 缓存目录: {CACHE_DIR}")
    logging.info(f"[Video] 处理文件: {video_path}")
    logging.info(f"[Video] 缓存文件: {thumb_path}")
    if os.path.exists(thumb_path):
        try:
            with Image.open(thumb_path) as img:
                logging.info(f"[Video] 命中缓存，直接返回: {thumb_path}")
                return thumb_path, img.size
        except Exception:
            logging.info(f"[Video] 缓存损坏，重新生成: {thumb_path}")
    try:
        cap = cv2.VideoCapture(video_path)
        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        thumb_w, thumb_h = get_scaled_size(orig_w, orig_h, max_size)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames == 0:
            logging.error(f"[Video] 视频无帧: {video_path}")
            return None, (max_size, max_size)
        # 均匀抽帧
        frame_indices = [int(i * total_frames / target_frames) for i in range(target_frames)]
        frames = []
        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame)
            img = img.resize((thumb_w, thumb_h), Image.LANCZOS)
            frames.append(img)
        cap.release()
        if frames:
            imageio.mimsave(thumb_path, frames, format='GIF', duration=1)
            logging.info(f"[Video] 生成新缓存: {thumb_path}")
            return thumb_path, (thumb_w, thumb_h)
    except Exception as e:
        logging.error(f"[Video] 生成GIF失败: {e}")
    return None, (max_size, max_size)

def open_file(filepath):
    if sys.platform.startswith('darwin'):
        subprocess.call(('open', filepath))
    elif os.name == 'nt':
        os.startfile(filepath)
    elif os.name == 'posix':
        subprocess.call(('xdg-open', filepath))

class FileListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListWidget.IconMode)
        self.setResizeMode(QListWidget.Adjust)
        self.setSpacing(16)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        # 用ThumbnailWidget作为预览窗口
        self.preview_widget = None
        self.setIconSize(QSize(1, 1))  # 不用icon

    def show_preview(self, thumb_path, tsize, is_gif):
        if self.preview_widget:
            self.preview_widget.close()
            self.preview_widget = None
        # 放大预览尺寸
        max_preview = 384
        # tsize 可能是QSize对象
        if hasattr(tsize, 'width') and hasattr(tsize, 'height'):
            w, h = tsize.width(), tsize.height()
        else:
            w, h = tsize
        scale = min(2, max_preview / w, max_preview / h)  # 放大2倍但不超过max_preview
        preview_size = (max(1, int(w * scale)), max(1, int(h * scale)))
        self.preview_widget = ThumbnailWidget(
            thumb_path, preview_size, fname='', is_gif=is_gif, show_name=False
        )
        self.preview_widget.setWindowFlags(Qt.ToolTip)
        self.preview_widget.show()

    def hide_preview(self):
        if self.preview_widget:
            self.preview_widget.close()
            self.preview_widget = None

class ThumbnailWidget(QWidget):
    def __init__(self, thumb_path, tsize, fname='', is_gif=False, show_name=True, parent=None):
        super().__init__(parent)
        self.thumb_path = thumb_path
        self.is_gif = is_gif
        self.fname = fname
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self.img_label = QLabel()
        self.img_label.setFixedSize(tsize[0], tsize[1])
        self.img_label.setAlignment(Qt.AlignCenter)
        if is_gif:
            self.movie = QMovie(thumb_path)
            self.img_label.setMovie(self.movie)
            self.movie.start()
        else:
            pix = QPixmap(thumb_path)
            self.img_label.setPixmap(pix)
        layout.addWidget(self.img_label)
        if show_name and fname:
            self.text_label = QLabel(fname)
            self.text_label.setAlignment(Qt.AlignCenter)
            self.text_label.setStyleSheet('font-size:10pt;')
            layout.addWidget(self.text_label)
        self.setLayout(layout)
        self.setFixedSize(tsize[0]+8, tsize[1]+(28 if show_name and fname else 8))

    def enterEvent(self, event):
        # 触发大图预览
        parent = self.parent()
        while parent and not isinstance(parent, FileListWidget):
            parent = parent.parent()
        if parent:
            global_pos = self.mapToGlobal(self.rect().topRight())
            parent.show_preview(self.thumb_path, self.img_label.size(), self.is_gif)
            if parent.preview_widget:
                parent.preview_widget.move(global_pos.x() + 20, global_pos.y())
        super().enterEvent(event)

    def leaveEvent(self, event):
        parent = self.parent()
        while parent and not isinstance(parent, FileListWidget):
            parent = parent.parent()
        if parent:
            parent.hide_preview()
        super().leaveEvent(event)

class ScanWorker(QThread):
    scanFinished = pyqtSignal(list)
    def __init__(self, dir_path):
        super().__init__()
        self.dir_path = dir_path
    def run(self):
        file_items = []
        for root, _, files in os.walk(self.dir_path):
            for fname in files:
                fpath = os.path.join(root, fname)
                ext = os.path.splitext(fname)[1].lower()
                if ext in IMAGE_EXTS:
                    thumb, tsize = generate_image_thumbnail(fpath, max_size=256)
                    if thumb:
                        file_items.append({'type': 'image', 'path': fpath, 'thumb': thumb, 'tsize': tsize})
                elif ext in VIDEO_EXTS:
                    thumb, tsize = generate_video_gif(fpath, max_size=256, target_frames=16, fps=8)
                    if thumb:
                        file_items.append({'type': 'video', 'path': fpath, 'thumb': thumb, 'tsize': tsize})
        self.scanFinished.emit(file_items)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("多媒体文件浏览器（缩略图+悬停预览+单击打开）")
        self.resize(1100, 700)
        self.list_widget = FileListWidget()
        btn = QPushButton("选择目录")
        btn.clicked.connect(self.select_dir)
        layout = QVBoxLayout()
        layout.addWidget(btn)
        layout.addWidget(self.list_widget)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.list_widget.itemClicked.connect(self.open_item)
        self.worker = None

    def select_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择目录")
        if dir_path:
            self.list_widget.clear()
            self.setWindowTitle(f"多媒体文件浏览器 - {dir_path}")
            self.statusBar().showMessage("正在扫描和生成缩略图，请稍候...")
            self.worker = ScanWorker(dir_path)
            self.worker.scanFinished.connect(self.on_scan_done)
            self.worker.start()

    def on_scan_done(self, file_items):
        self.list_widget.clear()
        for item in file_items:
            lw_item = QListWidgetItem()
            lw_item.thumb_path = item['thumb']
            lw_item.is_gif = (item['type'] == 'video')
            lw_item.tsize = item['tsize']
            lw_item.setSizeHint(QSize(item['tsize'][0]+8, item['tsize'][1]+28))
            lw_item.setData(Qt.UserRole, item['path'])
            self.list_widget.addItem(lw_item)
            widget = ThumbnailWidget(
                item['thumb'], item['tsize'], os.path.basename(item['path']),
                lw_item.is_gif
            )
            self.list_widget.setItemWidget(lw_item, widget)
        self.statusBar().showMessage(f"共{len(file_items)}个多媒体文件。")

    def open_item(self, item):
        fpath = item.data(Qt.UserRole)
        open_file(fpath)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_()) 