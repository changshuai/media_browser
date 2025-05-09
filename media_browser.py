# -*- coding: utf-8 -*-
# media_browser.py version: 1.0

import sys, os, hashlib, tempfile, threading
from PyQt5.QtWidgets import (QApplication, QMainWindow, QFileDialog, QListWidget, QListWidgetItem, QLabel, QVBoxLayout, QWidget, QPushButton, QHBoxLayout, QAbstractItemView, QSplitter, QTreeView, QFileSystemModel)
from PyQt5.QtGui import QPixmap, QIcon, QMovie
from PyQt5.QtCore import Qt, QSize, QEvent, QThread, pyqtSignal, QUrl, QTimer, QDir, QThreadPool, QRunnable, pyqtSlot, QObject
from PIL import Image
import cv2
import imageio
import subprocess
import logging
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget

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

class VideoPreviewWidget(QWidget):
    def __init__(self, video_path, parent=None, n_segments=8, segment_duration=1000):
        super().__init__(parent)
        self.setWindowFlags(Qt.ToolTip)
        self.setFixedSize(640, 360)  # 更大的16:9预览窗口
        self.player = QMediaPlayer(self)
        self.video_widget = QVideoWidget(self)
        self.player.setVideoOutput(self.video_widget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video_widget)
        self.setLayout(layout)
        self.video_path = video_path
        self.n_segments = n_segments
        self.segment_duration = segment_duration  # 每段播放时长（毫秒）
        self.jump_points = []
        self.current_jump = 0
        self.ready = False
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(video_path)))
        self.player.setMuted(True)
        self.player.play()
    def on_media_status_changed(self, status):
        print(f"media status changed: {status}")
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia) and not self.ready:
            total_duration = self.player.duration()
            print(f"total_duration: {total_duration}")
            if total_duration > 0:
                self.jump_points = [int(i * total_duration / self.n_segments) for i in range(self.n_segments)]
                print(f"jump_points: {self.jump_points}")
                self.current_jump = 0
                self.player.setPosition(self.jump_points[0])
                self.ready = True
    def on_position_changed(self, pos):
        print(f"position changed: {pos}, current_jump: {self.current_jump}")
        if self.ready and self.current_jump < len(self.jump_points):
            if pos - self.jump_points[self.current_jump] > self.segment_duration:
                self.current_jump += 1
                if self.current_jump < len(self.jump_points):
                    print(f"jumping to: {self.jump_points[self.current_jump]}")
                    self.player.setPosition(self.jump_points[self.current_jump])
                else:
                    self.current_jump = 0
                    print(f"looping to: {self.jump_points[0]}")
                    self.player.setPosition(self.jump_points[0])
    def closeEvent(self, event):
        self.player.stop()
        super().closeEvent(event)

class FileListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListWidget.IconMode)
        self.setResizeMode(QListWidget.Adjust)
        self.setSpacing(16)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.preview_widget = None
        self.setIconSize(QSize(1, 1))  # 不用icon

    def show_preview(self, thumb_path, tsize, is_gif, video_path=None):
        if self.preview_widget:
            self.preview_widget.close()
            self.preview_widget = None
        if is_gif and video_path:
            # 快进式视频预览
            self.preview_widget = VideoPreviewWidget(video_path, n_segments=5, segment_duration=1000)
        else:
            max_preview = 384
            if hasattr(tsize, 'width') and hasattr(tsize, 'height'):
                w, h = tsize.width(), tsize.height()
            else:
                w, h = tsize
            scale = min(2, max_preview / w, max_preview / h)
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
    def __init__(self, thumb_path, tsize, fname='', is_gif=False, show_name=True, parent=None, video_path=None):
        super().__init__(parent)
        self.thumb_path = thumb_path
        self.is_gif = is_gif
        self.fname = fname
        self.video_path = video_path
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self.img_label = QLabel()
        self.img_label.setFixedSize(tsize[0], tsize[1])
        self.img_label.setAlignment(Qt.AlignCenter)
        if is_gif:
            pix = QPixmap(thumb_path)
            self.img_label.setPixmap(pix)
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
        parent = self.parent()
        while parent and not isinstance(parent, FileListWidget):
            parent = parent.parent()
        if parent:
            global_pos = self.mapToGlobal(self.rect().topRight())
            if self.is_gif and self.video_path:
                parent.show_preview(self.thumb_path, self.img_label.size(), self.is_gif, video_path=self.video_path)
            else:
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

class ThumbWorkerSignals(QObject):
    finished = pyqtSignal(str, str, tuple, str, bool)  # fpath, thumb_path, tsize, fname, is_gif

class ThumbWorker(QRunnable):
    def __init__(self, fpath, is_gif):
        super().__init__()
        self.fpath = fpath
        self.is_gif = is_gif
        self.signals = ThumbWorkerSignals()

    @pyqtSlot()
    def run(self):
        if self.is_gif:
            thumb, tsize = generate_video_gif(self.fpath, max_size=256, target_frames=16, fps=8)
        else:
            thumb, tsize = generate_image_thumbnail(self.fpath, max_size=256)
        fname = os.path.basename(self.fpath)
        self.signals.finished.emit(self.fpath, thumb, tsize, fname, self.is_gif)

class MainWindow(QMainWindow):
    def __init__(self, root_dir):
        super().__init__()
        self.setWindowTitle("多媒体文件浏览器（目录树+异步缩略图）")
        self.resize(1200, 800)
        self.threadpool = QThreadPool()
        self.item_map = {}  # fpath -> QListWidgetItem

        # 左侧目录树
        self.dir_model = QFileSystemModel()
        self.dir_model.setRootPath(root_dir)
        self.dir_model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot)
        self.tree = QTreeView()
        self.tree.setModel(self.dir_model)
        self.tree.setRootIndex(self.dir_model.index(root_dir))  # 只显示你选择的目录及其子目录
        self.tree.setHeaderHidden(True)
        self.tree.clicked.connect(self.on_dir_selected)

        # 右侧缩略图列表
        self.list_widget = FileListWidget()

        # 布局
        splitter = QSplitter()
        splitter.addWidget(self.tree)
        splitter.addWidget(self.list_widget)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 900])
        self.setCentralWidget(splitter)

    def on_dir_selected(self, index):
        dir_path = self.dir_model.filePath(index)
        self.list_widget.clear()
        self.load_dir_files(dir_path)

    def load_dir_files(self, dir_path):
        self.item_map.clear()
        for fname in os.listdir(dir_path):
            fpath = os.path.join(dir_path, fname)
            if os.path.isfile(fpath):
                is_gif = fname.lower().endswith(VIDEO_EXTS)
                lw_item = QListWidgetItem(QIcon(), fname)
                lw_item.setData(Qt.UserRole, fpath)
                lw_item.is_gif = is_gif
                self.list_widget.addItem(lw_item)
                self.item_map[fpath] = lw_item
                worker = ThumbWorker(fpath, is_gif)
                worker.signals.finished.connect(self.on_thumb_ready)
                self.threadpool.start(worker)

    def on_thumb_ready(self, fpath, thumb_path, tsize, fname, is_gif):
        lw_item = self.item_map.get(fpath)
        if lw_item and thumb_path:
            widget = ThumbnailWidget(thumb_path, tsize, fname, is_gif, video_path=fpath if is_gif else None)
            self.list_widget.setItemWidget(lw_item, widget)
            lw_item.setSizeHint(QSize(tsize[0]+8, tsize[1]+28))

    def open_item(self, item):
        fpath = item.data(Qt.UserRole)
        open_file(fpath)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    # 先弹出目录选择
    root_dir = QFileDialog.getExistingDirectory(None, "请选择媒体库根目录")
    if not root_dir:
        sys.exit(0)
    win = MainWindow(root_dir)
    win.show()
    sys.exit(app.exec_()) 