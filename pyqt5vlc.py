import json
import sys
import time

import requests
import vlc
from PyQt6.QtCore import Qt, QSize, QTimer, QSettings, QThread, QMetaObject, Q_ARG, pyqtSignal, QEvent
from PyQt6.QtGui import QIcon, QKeySequence, QAction, QColor, QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget, QLabel, QPushButton, QSlider, QHBoxLayout, QInputDialog, QStyle, QSplitter
)


class FileItem(QListWidgetItem):
    def __init__(self, name, fid, file_type, size, icon):
        if len(size) > 0:
            text = name + " (" + size + ")"
        else:
            text = name
        super().__init__(icon, text)
        self.fid = fid
        self.name = name
        self.file_type = file_type
        self.is_playing = False  # 添加播放状态标志
        self.normal_font = QFont()  # 普通字体
        self.bold_font = QFont()  # 加粗字体
        self.bold_font.setBold(True)

    def set_playing(self, playing):
        """设置播放状态并更新样式"""
        self.is_playing = playing
        self.update_style()

    def update_style(self):
        """根据播放状态更新样式"""
        if self.is_playing:
            self.setBackground(QColor(30, 144, 255))  # 蓝色背景
            self.setForeground(QColor(255, 255, 255))  # 白色文字
            self.setFont(self.bold_font)  # 加粗字体
        else:
            self.setBackground(QColor(0, 0, 0, 0))  # 透明背景
            self.setForeground(QColor(0, 0, 0))  # 黑色文字
            self.setFont(self.normal_font)  # 普通字体


class AtvPlayer(QMainWindow):
    media_finished_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.media_finished_signal.connect(self._handle_media_finished_async)
        # Initialize settings
        self.settings = QSettings("AtvPlayer", "Config")

        # Load saved API address or prompt for it
        self.api = self.settings.value("api_address", "")
        if not self.api:
            self.prompt_api_address()

        # Initialize other properties with saved values or defaults
        self.current_path = self.settings.value("current_path", "1$/$1")
        self.path_history = json.loads(self.settings.value("path_history", "[]"))
        # 恢复播放状态
        self.last_played_fid = self.settings.value("last_played_fid", "")
        self.last_played_position = int(self.settings.value("last_played_position", 0))
        self.last_played_path = self.settings.value("last_played_path", "")
        self.is_playing = False
        self.is_fullscreen = False
        self.is_show_list = True
        self.media_duration = 0
        self.current_position = 0
        self.current_media_index = -1  # Track currently playing item index

        # Initialize icons
        self.folder_icon = QIcon.fromTheme("folder", self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self.file_icon = QIcon.fromTheme("video-x-generic",
                                         self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        self.toggle_icon_show = QIcon.fromTheme("view-list",
                                                self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView))
        self.toggle_icon_hide = QIcon.fromTheme("view-list-hidden", self.style().standardIcon(
            QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.play_icon = QIcon.fromTheme("media-playback-start",
                                         self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.pause_icon = QIcon.fromTheme("media-playback-pause",
                                          self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        self.stop_icon = QIcon.fromTheme("media-playback-stop",
                                         self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.backward_icon = QIcon.fromTheme("media-skip-backward",
                                             self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSeekBackward))
        self.forward_icon = QIcon.fromTheme("media-skip-forward",
                                            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSeekForward))
        self.fullscreen_icon = QIcon.fromTheme("view-fullscreen")
        self.restore_icon = QIcon.fromTheme("view-restore")
        self.prev_icon = QIcon.fromTheme("go-previous")

        self.setWindowTitle("AList TvBox Player")
        self.resize(1920, 1080)
        self.showMaximized()

        # Initialize UI and player
        self.init_ui()
        self.init_player()
        self.init_shortcuts()
        self.init_menu()

        # Setup position timer
        self.position_timer = QTimer(self)
        self.position_timer.timeout.connect(self.update_position)
        self.position_timer.start(1000)

        # 鼠标控制相关
        self.mouse_timer = QTimer(self)
        self.mouse_timer.setSingleShot(True)
        self.mouse_timer.timeout.connect(lambda: self.set_mouse_visibility(False))

        # 如果上次有播放记录，尝试恢复
        if self.last_played_fid and self.last_played_path:
            QTimer.singleShot(1000, self.restore_playback)  # 延迟1秒确保UI加载完成
        else:
            self.load_files(self.current_path)

    def init_ui(self):
        # Main layout - vertical split between video+controls and file list
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left side - Video and controls (vertical layout)
        left_widget = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # Video widget - takes most space
        self.video_widget = QWidget()
        self.video_widget.setAutoFillBackground(True)
        palette = self.video_widget.palette()
        palette.setColor(self.video_widget.backgroundRole(), Qt.GlobalColor.black)
        self.video_widget.setPalette(palette)
        left_layout.addWidget(self.video_widget, stretch=1)

        # Controls container - takes less space
        self.controls_container = QWidget()
        controls_layout = QVBoxLayout()
        controls_layout.setContentsMargins(5, 5, 5, 5)

        # Progress container - horizontal with time and progress bar
        self.progress_container = QWidget()
        progress_layout = QHBoxLayout()
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(5)

        # Current time label (left)
        self.current_time_label = QLabel("00:00:00")
        self.current_time_label.setFixedWidth(60)
        progress_layout.addWidget(self.current_time_label)

        # Progress slider (center)
        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.sliderMoved.connect(self.seek_position)
        self.progress_slider.sliderPressed.connect(self.pause_for_seek)
        self.progress_slider.sliderReleased.connect(self.resume_after_seek)
        progress_layout.addWidget(self.progress_slider)

        # Duration label (right)
        self.duration_label = QLabel("00:00:00")
        self.duration_label.setFixedWidth(60)
        progress_layout.addWidget(self.duration_label)

        self.progress_container.setLayout(progress_layout)
        self.progress_container.setVisible(False)

        # Button controls - horizontal layout with fixed size buttons
        button_container = QWidget()
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(5)

        # Play/Pause button
        self.play_btn = QPushButton(self.play_icon, "")
        self.play_btn.clicked.connect(self.play_pause)
        self.play_btn.setToolTip("播放/暂停 (Space)")
        self.play_btn.setFixedSize(24, 24)
        button_layout.addWidget(self.play_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Previous button
        self.prev_btn = QPushButton(self.backward_icon, "")
        self.prev_btn.clicked.connect(self.play_previous)
        self.prev_btn.setToolTip("上一个 (PageUp)")
        self.prev_btn.setFixedSize(24, 24)
        button_layout.addWidget(self.prev_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Stop button
        self.stop_btn = QPushButton(self.stop_icon, "")
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setToolTip("停止")
        self.stop_btn.setFixedSize(24, 24)
        button_layout.addWidget(self.stop_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Next button
        self.next_btn = QPushButton(self.forward_icon, "")
        self.next_btn.clicked.connect(self.play_next)
        self.next_btn.setToolTip("下一个 (PageDown)")
        self.next_btn.setFixedSize(24, 24)
        button_layout.addWidget(self.next_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Toggle file list button
        self.toggle_list_btn = QPushButton(self.toggle_icon_hide, "")
        self.toggle_list_btn.clicked.connect(self.toggle_file_list)
        self.toggle_list_btn.setToolTip("显示/隐藏文件列表 (F9)")
        self.toggle_list_btn.setFixedSize(24, 24)
        button_layout.addWidget(self.toggle_list_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # 添加全屏按钮
        self.fullscreen_btn = QPushButton(self.fullscreen_icon, "")
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        self.fullscreen_btn.setToolTip("全屏 (F11)")
        self.fullscreen_btn.setFixedSize(24, 24)
        button_layout.addWidget(self.fullscreen_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Add stretch to push volume controls to the right
        button_layout.addStretch(1)

        # Volume controls
        volume_container = QWidget()
        volume_layout = QHBoxLayout()
        volume_layout.setContentsMargins(0, 0, 0, 0)
        volume_layout.setSpacing(5)

        volume_layout.addWidget(QLabel("音量:"))

        # 音量滑块
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(self.settings.value("volume", 50)))
        self.volume_slider.valueChanged.connect(self.set_volume)
        self.volume_slider.setFixedWidth(100)
        volume_layout.addWidget(self.volume_slider)

        # 音量数值显示
        self.volume_label = QLabel(str(self.volume_slider.value()))
        self.volume_label.setFixedWidth(30)  # 固定宽度避免布局跳动
        self.volume_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        volume_layout.addWidget(self.volume_label)

        volume_container.setLayout(volume_layout)
        button_layout.addWidget(volume_container)

        button_container.setLayout(button_layout)

        # Add controls to the layout
        controls_layout.addWidget(self.progress_container)
        controls_layout.addWidget(button_container)
        self.controls_container.setLayout(controls_layout)

        left_layout.addWidget(self.controls_container)
        left_widget.setLayout(left_layout)

        # Right side - File list with back button on top
        self.right_widget = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)

        # Back button moved to file list area
        self.back_btn = QPushButton(QIcon.fromTheme("go-previous"), "后退")
        self.back_btn.clicked.connect(self.go_back)
        self.back_btn.setEnabled(bool(self.path_history))
        self.back_btn.setToolTip("返回上一级目录")
        right_layout.addWidget(self.back_btn)

        # File list
        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(24, 24))
        self.list_widget.itemClicked.connect(self.on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)

        right_layout.addWidget(self.list_widget)
        self.right_widget.setLayout(right_layout)

        # Add both sides to splitter
        self.main_splitter = main_splitter  # Make splitter accessible for toggling
        self.main_splitter.addWidget(left_widget)
        self.main_splitter.addWidget(self.right_widget)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 1)

        # Status bar
        # self.status_bar = QStatusBar()
        # self.setStatusBar(self.status_bar)

        # Set central widget
        self.setCentralWidget(main_splitter)

        self.video_widget.setMouseTracking(True)  # 视频控件也需要启用
        self.video_widget.installEventFilter(self)

        self.update_buttons()

    def toggle_file_list(self):
        """Toggle visibility of the file list"""
        self.is_show_list = not self.is_show_list
        self.right_widget.setVisible(self.is_show_list)
        # 更新按钮图标
        if self.is_show_list:
            self.toggle_list_btn.setIcon(self.toggle_icon_hide)
            self.toggle_list_btn.setToolTip("隐藏文件列表 (F9)")
        else:
            self.toggle_list_btn.setIcon(self.toggle_icon_show)
            self.toggle_list_btn.setToolTip("显示文件列表 (F9)")

    def toggle_fullscreen(self):
        """切换全屏状态"""
        if self.isFullScreen():
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def exit_fullscreen(self):
        if not self.is_fullscreen:
            return
        self.is_fullscreen = False
        self.showNormal()
        # 显示所有控件
        self.menuBar().show()
        # self.status_bar.show()

        self.fullscreen_btn.setIcon(self.fullscreen_icon)
        self.fullscreen_btn.setToolTip("全屏")
        if hasattr(self, 'controls_container'):
            self.controls_container.setVisible(True)
        # 恢复文件列表可见性
        if hasattr(self, 'right_widget') and self.is_show_list:
            self.right_widget.setVisible(True)
        self.showMaximized()
        self.set_mouse_visibility(not self.is_playing)  # 退出全屏时根据播放状态设置鼠标

    def enter_fullscreen(self):
        self.is_fullscreen = True
        self.showFullScreen()
        # 隐藏所有非视频控件
        self.menuBar().hide()
        # self.status_bar.hide()

        self.fullscreen_btn.setIcon(self.restore_icon)
        self.fullscreen_btn.setToolTip("退出全屏")
        if hasattr(self, 'controls_container'):
            self.controls_container.setVisible(False)
        # 全屏时隐藏文件列表
        if hasattr(self, 'right_widget'):
            self.right_widget.setVisible(False)
        if self.is_playing:
            self.set_mouse_visibility(False)  # 进入全屏且播放时隐藏鼠标

    def init_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&选项")

        config_action = QAction("配置API地址", self)
        config_action.triggered.connect(self.prompt_api_address)
        file_menu.addAction(config_action)

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def prompt_api_address(self):
        """Prompt user for API address if not configured"""
        dialog = QInputDialog(self)
        dialog.setWindowTitle("API配置")
        dialog.setLabelText("输入Vod API地址:")
        dialog.setTextValue(self.api if hasattr(self, 'api') else "http://localhost:4567/vod")

        # 设置输入框宽度
        dialog.setMinimumWidth(400)  # 设置对话框最小宽度
        dialog.setStyleSheet("QLineEdit { min-width: 300px; }")  # 设置输入框最小宽度

        if dialog.exec() == QInputDialog.DialogCode.Accepted:
            address = dialog.textValue()
            if address:
                self.api = address
                self.settings.setValue("api_address", self.api)

    def show_status_message(self, message, timeout=2000, print_message=True):
        # self.status_bar.showMessage(message, timeout)
        if print_message:
            print(f"[STATUS] {message}")

    def init_player(self):
        self.instance = vlc.Instance("--no-xlib")
        self.player = self.instance.media_player_new()
        # Set video output to our widget
        if sys.platform.startswith('linux'):  # for Linux using the X Server
            self.player.set_xwindow((int(self.video_widget.winId())))
        elif sys.platform == "win32":  # for Windows
            self.player.set_hwnd(self.video_widget.winId())
        elif sys.platform == "darwin":  # for MacOS
            self.player.set_nsobject(int(self.video_widget.winId()))
        self.player.event_manager().event_attach(
            vlc.EventType.MediaPlayerEndReached,
            self._vlc_callback_wrapper  # 改用包装器
        )
        self.set_volume(self.volume_slider.value())  # Set from saved value

    def _vlc_callback_wrapper(self, event):
        """将VLC回调转发到Qt主线程"""
        self.media_finished_signal.emit()

    def _handle_media_finished_async(self):
        """在主线程中安全处理结束事件"""
        if self.list_widget.count() > 0:
            next_index = self.find_next_playable_item(self.current_media_index + 1)
            if next_index >= 0:
                QTimer.singleShot(100, lambda: self.play_item_at_index(next_index))  # 延迟避免重入
            else:
                self.stop()

    def save_playback_state(self):
        """保存当前播放状态到设置"""
        if hasattr(self, 'player') and self.player.get_media():
            self.settings.setValue("last_played_fid", self.last_played_fid)
            self.settings.setValue("last_played_position", self.player.get_time())
            self.settings.setValue("last_played_path", self.current_path)
            self.settings.sync()  # 立即写入磁盘

    def restore_playback(self):
        """恢复上次的播放状态"""
        try:
            if not self.last_played_fid or not self.last_played_path:
                return

            # 加载相同的目录
            self.load_files(self.last_played_path)

            # 查找上次播放的文件
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if isinstance(item, FileItem) and item.fid == self.last_played_fid:
                    self.current_media_index = i
                    self.list_widget.setCurrentItem(item)

                    # 获取播放URL并恢复播放
                    url = self.get_play_url(item.fid)
                    if url:
                        self.play_media(url, item.name)

                        # 恢复播放位置
                        if self.last_played_position > 0:
                            QTimer.singleShot(2000, lambda: self.player.set_time(self.last_played_position))
                    break
        except Exception as e:
            print(f"恢复播放失败: {str(e)}")

    def save_settings(self):
        """Save current state to settings"""
        self.settings.setValue("volume", self.player.audio_get_volume())
        self.settings.setValue("current_path", self.current_path)
        self.settings.setValue("path_history", json.dumps(self.path_history))

    def init_shortcuts(self):
        # Play/Pause toggle with Spacebar
        self.play_action = QAction(self)
        self.play_action.setShortcut(QKeySequence(Qt.Key.Key_Space))
        self.play_action.triggered.connect(self.play_pause)
        self.addAction(self.play_action)

        # Stop with Escape
        self.stop_action = QAction(self)
        self.stop_action.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        self.stop_action.triggered.connect(self.exit_fullscreen)
        self.addAction(self.stop_action)

        # Volume up/down with arrow keys
        self.vol_up_action = QAction(self)
        self.vol_up_action.setShortcut(QKeySequence(Qt.Key.Key_Up))
        self.vol_up_action.triggered.connect(self.volume_up)
        self.addAction(self.vol_up_action)

        self.vol_down_action = QAction(self)
        self.vol_down_action.setShortcut(QKeySequence(Qt.Key.Key_Down))
        self.vol_down_action.triggered.connect(self.volume_down)
        self.addAction(self.vol_down_action)

        # Seek forward/backward with Left/Right arrows
        self.seek_back_action = QAction(self)
        self.seek_back_action.setShortcut(QKeySequence(Qt.Key.Key_Left))
        self.seek_back_action.triggered.connect(lambda: self.seek_relative(-10))
        self.addAction(self.seek_back_action)

        self.seek_forward_action = QAction(self)
        self.seek_forward_action.setShortcut(QKeySequence(Qt.Key.Key_Right))
        self.seek_forward_action.triggered.connect(lambda: self.seek_relative(10))
        self.addAction(self.seek_forward_action)

        # 上一个/下一个快捷键
        self.prev_action = QAction(self)
        self.prev_action.setShortcut(QKeySequence(Qt.Key.Key_PageUp))
        self.prev_action.triggered.connect(self.play_previous)
        self.addAction(self.prev_action)

        self.next_action = QAction(self)
        self.next_action.setShortcut(QKeySequence(Qt.Key.Key_PageDown))
        self.next_action.triggered.connect(self.play_next)
        self.addAction(self.next_action)

        # 添加全屏快捷键(F11)
        self.fullscreen_action = QAction(self)
        self.fullscreen_action.setShortcut(QKeySequence(Qt.Key.Key_F11))
        self.fullscreen_action.triggered.connect(self.toggle_fullscreen)
        self.addAction(self.fullscreen_action)

        self.list_action = QAction(self)
        self.list_action.setShortcut(QKeySequence(Qt.Key.Key_F9))
        self.list_action.triggered.connect(self.toggle_file_list)
        self.addAction(self.list_action)

    def update_buttons(self):
        """Update button states based on player status"""
        if self.is_playing:
            self.play_btn.setIcon(self.pause_icon)
            # self.play_btn.setText("暂停")
        else:
            self.play_btn.setIcon(self.play_icon)
            # self.play_btn.setText("播放")
        self.stop_btn.setEnabled(self.is_playing)

        has_items = self.list_widget.count() > 0
        self.prev_btn.setEnabled(has_items and self.current_media_index > 0)
        self.next_btn.setEnabled(has_items and self.current_media_index < self.list_widget.count() - 1)

    def eventFilter(self, obj, event):
        if obj == self.video_widget and event.type() == QEvent.Type.MouseMove:
            if self.is_playing:
                self.set_mouse_visibility(True)
                self.mouse_timer.start(3000)
        return super().eventFilter(obj, event)

    def set_mouse_visibility(self, visible):
        """设置鼠标指针可见性"""
        cursor = Qt.CursorShape.ArrowCursor if visible else Qt.CursorShape.BlankCursor
        self.video_widget.setCursor(cursor)

    def set_volume(self, volume):
        """Set volume (0-100) and update slider"""
        if 0 <= volume <= 100:
            self.player.audio_set_volume(volume)
            self.volume_slider.blockSignals(True)
            self.volume_slider.setValue(volume)
            self.volume_slider.blockSignals(False)
            self.volume_label.setText(str(volume))
            self.save_settings()

    def volume_up(self):
        """Increase volume by 5"""
        current = self.player.audio_get_volume()
        self.set_volume(min(100, current + 5))

    def volume_down(self):
        """Decrease volume by 5"""
        current = self.player.audio_get_volume()
        self.set_volume(max(0, current - 5))

    def play_pause(self):
        """Handle both initial play and pause/resume"""
        if not self.player.get_media():  # 首次播放
            self.play_selected_item()
        else:  # 暂停/继续
            if self.player.is_playing():
                self.player.pause()
                self.is_playing = False
                self.set_mouse_visibility(True)  # 暂停时显示鼠标
            else:
                self.player.play()
                self.is_playing = True
                self.set_mouse_visibility(False)  # 播放时隐藏鼠标
        self.update_buttons()

    def stop(self):
        """Stop playback"""
        self.player.stop()
        media = self.player.get_media()
        if media:
            media.release()
            self.player.set_media(None)  # 清空媒体引用
        self.is_playing = False
        self.progress_container.setVisible(False)
        self.set_mouse_visibility(True)  # 停止时显示鼠标
        self.setWindowTitle("AList TvBox Player")
        # 清除高亮状态
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if isinstance(item, FileItem):
                item.set_playing(False)
        if self.isFullScreen():
            self.exit_fullscreen()
        self.update_buttons()
        self.show_status_message("停止播放", 2000)

    def add_file_item(self, name, fid, file_type, size):
        """Add a file or folder item with appropriate icon"""
        icon = self.folder_icon if file_type == 1 else self.file_icon
        item = FileItem(name, fid, file_type, size, icon)
        self.list_widget.addItem(item)

    def load_files(self, path):
        self.show_status_message("加载中...")
        QApplication.processEvents()

        url = f"{self.api}?ac=web&t={path}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            files = response.json().get("list", [])

            self.list_widget.clear()
            if not files:
                self.show_status_message("没有文件", 3000)
                return

            for file in files:
                if file["type"] != 9:
                    self.add_file_item(file["vod_name"], file["vod_id"], file["type"], file["vod_remarks"])

            self.current_path = path
            self.save_settings()
            # self.show_status_message(f"已加载: {path}", 3000)

        except requests.RequestException as e:
            self.show_status_message(f"加载文件错误: {str(e)}", 5000)
        except Exception as e:
            self.show_status_message(f"错误: {str(e)}", 5000)

    def get_play_url(self, fid):
        url = f"{self.api}?ac=web&ids={fid}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            files = response.json().get("list", [])
            if files:
                return files[0]["vod_play_url"]
        except Exception as e:
            self.show_status_message(f"获取播放地址错误: {str(e)}", 5000)
        return None

    def on_media_finished(self, event):
        """Called when current media finishes playing"""
        print('on_media_finished')
        if self.list_widget.count() > 0:
            # Find next playable item
            next_index = self.find_next_playable_item(self.current_media_index + 1)
            print(f'next index: {next_index}')
            if next_index >= 0:
                self.play_item_at_index(next_index)
            else:
                self.stop()
                self.show_status_message("播放完毕", 3000)
        else:
            self.list_widget.clearSelection()  # Clear highlight if no items

    def find_next_playable_item(self, start_index):
        """Find next playable video file starting from given index"""
        for i in range(start_index, self.list_widget.count()):
            item = self.list_widget.item(i)
            if isinstance(item, FileItem) and item.file_type != 1:  # Skip directories
                return i
        return -1  # No playable items found

    def play_item_at_index(self, index):
        """Play the item at specified index in the list"""
        if not QThread.currentThread() == self.thread():
            QMetaObject.invokeMethod(self, "play_item_at_index",
                                     Qt.ConnectionType.QueuedConnection,
                                     Q_ARG(int, index))
            return
        item = self.list_widget.item(index)
        if isinstance(item, FileItem) and item.file_type != 1:  # Only play files
            self.current_media_index = index
            url = self.get_play_url(item.fid)
            if url:
                self.play_media(url, item.name)
                # 先清除所有选择
                self.list_widget.clearSelection()
                QApplication.processEvents()  # 强制刷新UI

                # 设置新选择并确保可见
                self.list_widget.setCurrentItem(item)
                self.list_widget.scrollToItem(item, QListWidget.ScrollHint.PositionAtCenter)

    def play_selected_item(self):
        """Play the currently selected item in the list"""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            # 尝试自动选择第一个可播放文件
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if isinstance(item, FileItem) and item.file_type != 1:
                    self.list_widget.setCurrentItem(item)
                    self.current_media_index = i
                    url = self.get_play_url(item.fid)
                    if url:
                        return self.play_media(url, item.name)

            self.show_status_message("No playable files found", 3000)
            return

        item = selected_items[0]  # 获取第一个选中项
        if isinstance(item, FileItem) and item.file_type != 1:  # 确保是文件
            self.current_media_index = self.list_widget.row(item)
            url = self.get_play_url(item.fid)
            if url:
                self.play_media(url, item.name)
        else:
            self.show_status_message("无媒体文件", 3000)

    def play_next(self):
        """播放下一个有效视频文件"""
        if self.list_widget.count() == 0:
            return

        next_index = self.find_playable_item(self.current_media_index + 1)
        if next_index >= 0:
            self.play_item_at_index(next_index)
        else:
            self.show_status_message("已是最后一个视频", 2000)

    def play_previous(self):
        """播放上一个有效视频文件"""
        if self.list_widget.count() == 0:
            return

        prev_index = self.find_playable_item(self.current_media_index - 1, reverse=True)
        if prev_index >= 0:
            self.play_item_at_index(prev_index)
        else:
            self.show_status_message("已是第一个视频", 2000)

    def find_playable_item(self, start_index, reverse=False):
        """
        查找可播放的项目
        :param start_index: 起始索引
        :param reverse: 是否反向查找
        :return: 找到的索引，-1表示未找到
        """
        step = -1 if reverse else 1
        for i in range(start_index,
                       len(self.list_widget) if not reverse else -1,
                       step):
            item = self.list_widget.item(i)
            if isinstance(item, FileItem) and item.file_type != 1:  # 跳过文件夹
                return i
        return -1

    def play_media(self, url, title):
        """Start playback with proper initialization"""
        # 清除之前的媒体
        if self.player.get_media():
            self.player.stop()

        media = self.instance.media_new(url)
        self.player.set_media(media)
        self.player.play()
        self.is_playing = True

        # UI 更新
        self.progress_container.setVisible(True)
        self.update_buttons()

        self.setWindowTitle(f"正在播放: {title}")
        self.show_status_message(f"开始播放: {title}", 3000)

        # 强制刷新选中状态
        self.list_widget.clearSelection()
        item = self.list_widget.item(self.current_media_index)
        # item.setSelected(True)
        self.list_widget.scrollToItem(item)

        # 保存当前播放的文件ID
        if isinstance(item, FileItem):
            self.last_played_fid = item.fid
            self.save_playback_state()

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if isinstance(item, FileItem):
                item.set_playing(i == self.current_media_index)

    def update_position(self):
        """Update the position slider and time labels"""
        if self.player.is_playing():
            # Get current position and duration in milliseconds
            position = self.player.get_time()
            duration = self.player.get_length()

            # 每5秒保存一次播放进度
            if int(time.time()) % 5 == 0:
                self.save_playback_state()

            if duration > 0:
                # Update slider position (0-1000)
                self.progress_slider.setValue(int(1000 * position / duration))

                # Update time labels
                self.current_time_label.setText(self.format_time(position))
                self.duration_label.setText(self.format_time(duration))

    def format_time(self, ms):
        """Convert milliseconds to HH:MM:SS format"""
        seconds = int(ms / 1000)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def seek_position(self, value):
        """Seek to a specific position in the media"""
        if self.player.get_media():
            # Convert slider value (0-1000) to milliseconds
            duration = self.player.get_length()
            position = int(duration * value / 1000)
            self.player.set_time(position)

    def seek_relative(self, seconds):
        """Seek forward or backward by specified seconds"""
        if self.player.get_media():
            current_pos = self.player.get_time()
            new_pos = current_pos + (seconds * 1000)
            duration = self.player.get_length()

            # Ensure we don't seek beyond media boundaries
            new_pos = max(0, min(new_pos, duration))
            self.player.set_time(new_pos)

    def pause_for_seek(self):
        """Pause playback while seeking"""
        if self.player.is_playing():
            self.was_playing = True
            self.player.pause()
        else:
            self.was_playing = False

    def resume_after_seek(self):
        """Resume playback after seeking"""
        if self.was_playing:
            self.player.play()

    def on_item_clicked(self, item):
        if isinstance(item, FileItem):
            if item.file_type == 1:  # Directory
                self.path_history.append(self.current_path)
                self.back_btn.setEnabled(True)
                self.save_settings()
                self.load_files(item.fid)

    def on_item_double_clicked(self, item):
        if isinstance(item, FileItem):
            if item.file_type != 1:
                self.current_media_index = self.list_widget.row(item)
                url = self.get_play_url(item.fid)
                if url:
                    self.play_media(url, item.name)

    def go_back(self):
        if self.path_history:
            prev_path = self.path_history.pop()
            self.save_settings()
            self.load_files(prev_path)
            self.back_btn.setEnabled(bool(self.path_history))

    def closeEvent(self, event):
        # 正常停止播放
        if hasattr(self, 'player') and self.player.is_playing():
            self.save_playback_state()
        if hasattr(self, 'player'):
            self.player.stop()
            self.player.release()

        # 确保设置已写入磁盘
        self.settings.sync()
        event.accept()


if __name__ == "__main__":
    app = QApplication([])
    window = AtvPlayer()
    window.show()
    app.exec()
