import json

import requests
import vlc
from PyQt6.QtCore import Qt, QSize, QTimer, QSettings, QThread, QMetaObject, Q_ARG, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QIcon, QKeySequence, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget, QLabel, QStatusBar, QToolBar,
    QPushButton, QSlider, QHBoxLayout, QInputDialog, QStyle
)


class FileItem(QListWidgetItem):
    def __init__(self, name, fid, file_type, icon):
        super().__init__(icon, name)
        self.fid = fid
        self.file_type = file_type


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
        self.is_playing = False
        self.is_stop = True
        self.media_duration = 0
        self.current_position = 0
        self.current_media_index = -1  # Track currently playing item index

        # Initialize icons
        self.folder_icon = QIcon.fromTheme("folder")
        self.file_icon = QIcon.fromTheme("video-x-generic")

        # Fallback icons if theme icons are not available
        if self.folder_icon.isNull():
            self.folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        if self.file_icon.isNull():
            self.file_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

        self.setWindowTitle("AList TvBox Player")
        self.resize(800, 600)

        # Initialize UI and player
        self.init_ui()
        self.init_player()
        self.init_shortcuts()
        self.init_menu()

        # Setup position timer
        self.position_timer = QTimer(self)
        self.position_timer.timeout.connect(self.update_position)
        self.position_timer.start(1000)

        # Load initial files
        self.load_files(self.current_path)

    def init_ui(self):
        # Main toolbar
        toolbar = QToolBar("Main Controls")
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(toolbar)

        # Navigation controls
        self.back_btn = QPushButton(QIcon.fromTheme("go-previous"), "后退")
        self.back_btn.clicked.connect(self.go_back)
        self.back_btn.setEnabled(bool(self.path_history))
        toolbar.addWidget(self.back_btn)

        # 上一个按钮
        self.prev_btn = QPushButton(QIcon.fromTheme("media-skip-backward"), "上一个")
        self.prev_btn.clicked.connect(self.play_previous)
        toolbar.addWidget(self.prev_btn)

        # Media controls
        self.play_btn = QPushButton(QIcon.fromTheme("media-playback-start"), "播放")
        self.play_btn.clicked.connect(self.play_pause)
        toolbar.addWidget(self.play_btn)

        self.stop_btn = QPushButton(QIcon.fromTheme("media-playback-stop"), "停止")
        self.stop_btn.clicked.connect(self.stop)
        toolbar.addWidget(self.stop_btn)

        # 下一个按钮
        self.next_btn = QPushButton(QIcon.fromTheme("media-skip-forward"), "下一个")
        self.next_btn.clicked.connect(self.play_next)
        toolbar.addWidget(self.next_btn)

        # Volume controls
        toolbar.addSeparator()
        toolbar.addWidget(QLabel("音量:"))

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(self.settings.value("volume", 50)))
        self.volume_slider.valueChanged.connect(self.set_volume)
        self.volume_slider.setFixedWidth(100)
        toolbar.addWidget(self.volume_slider)

        # Progress bar and time display
        self.progress_container = QWidget()
        progress_layout = QVBoxLayout()

        # Time labels
        self.time_container = QWidget()
        time_layout = QHBoxLayout()
        self.current_time_label = QLabel("00:00:00")
        self.duration_label = QLabel("00:00:00")
        time_layout.addWidget(self.current_time_label)
        time_layout.addStretch()
        time_layout.addWidget(self.duration_label)
        self.time_container.setLayout(time_layout)

        # Progress slider
        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.sliderMoved.connect(self.seek_position)
        self.progress_slider.sliderPressed.connect(self.pause_for_seek)
        self.progress_slider.sliderReleased.connect(self.resume_after_seek)

        progress_layout.addWidget(self.time_container)
        progress_layout.addWidget(self.progress_slider)
        self.progress_container.setLayout(progress_layout)
        self.progress_container.setVisible(False)

        # File list
        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(32, 32))  # Set appropriate icon size
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Main layout
        layout = QVBoxLayout()
        layout.addWidget(self.progress_container)
        layout.addWidget(self.list_widget)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.update_buttons()

    def init_menu(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&选项")

        config_action = QAction("配置API地址", self)
        config_action.triggered.connect(self.prompt_api_address)
        file_menu.addAction(config_action)

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def prompt_api_address(self):
        """Prompt user for API address if not configured"""
        address, ok = QInputDialog.getText(
            self,
            "API配置",
            "输入API地址:",
            text=self.api if hasattr(self, 'api') else "http://localhost:4567/vod"
        )
        if ok and address:
            self.api = address
            self.settings.setValue("api_address", self.api)
            # self.show_status_message("API address updated", 3000)

    def show_status_message(self, message, timeout=2000, print_message=True):
        self.status_bar.showMessage(message, timeout)
        if print_message:
            print(f"[STATUS] {message}")

    def init_player(self):
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()
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

    def _on_vlc_window_closed(self, event):
        """VLC窗口关闭时的回调函数"""
        # 通过信号槽转到主线程处理
        QMetaObject.invokeMethod(self,
                                 "_handle_window_closed",
                                 Qt.ConnectionType.QueuedConnection)

    @pyqtSlot()
    def _handle_window_closed(self):
        """主线程安全处理窗口关闭"""
        if self.player.is_playing():
            self.stop()
            self.show_status_message("播放窗口已关闭，停止播放", 3000)

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
        self.stop_action.triggered.connect(self.stop)
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

    def update_buttons(self):
        """Update button states based on player status"""
        if self.is_playing:
            self.play_btn.setIcon(QIcon.fromTheme("media-playback-pause"))
            self.play_btn.setText("暂停")
        else:
            self.play_btn.setIcon(QIcon.fromTheme("media-playback-start"))
            self.play_btn.setText("播放")
        self.stop_btn.setEnabled(self.is_playing)

        has_items = self.list_widget.count() > 0
        self.prev_btn.setEnabled(has_items and self.current_media_index > 0)
        self.next_btn.setEnabled(has_items and self.current_media_index < self.list_widget.count() - 1)

    def set_volume(self, volume):
        """Set volume (0-100) and update slider"""
        if 0 <= volume <= 100:
            self.player.audio_set_volume(volume)
            self.volume_slider.blockSignals(True)
            self.volume_slider.setValue(volume)
            self.volume_slider.blockSignals(False)
            self.show_status_message(f"音量: {volume}%", 2000)
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
                self.is_stop = False
            else:
                self.player.play()
                self.is_playing = True
                self.is_stop = False
        self.update_buttons()

    def stop(self):
        """Stop playback"""
        self.player.stop()
        media = self.player.get_media()
        if media:
            media.release()
            self.player.set_media(None)  # 清空媒体引用
        self.is_playing = False
        self.is_stop = True
        self.progress_container.setVisible(False)
        self.setWindowTitle("AList TvBox Player")
        self.update_buttons()
        self.show_status_message("停止播放", 2000)

    def add_file_item(self, name, fid, file_type):
        """Add a file or folder item with appropriate icon"""
        icon = self.folder_icon if file_type == 1 else self.file_icon
        item = FileItem(name, fid, file_type, icon)
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
                    self.add_file_item(file["vod_name"], file["vod_id"], file["type"])

            self.current_path = path
            self.save_settings()
            #self.show_status_message(f"已加载: {path}", 3000)

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
                self.play_media(url, item.text())
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
                        return self.play_media(url, item.text())

            self.show_status_message("No playable files found", 3000)
            return

        item = selected_items[0]  # 获取第一个选中项
        if isinstance(item, FileItem) and item.file_type != 1:  # 确保是文件
            self.current_media_index = self.list_widget.row(item)
            url = self.get_play_url(item.fid)
            if url:
                self.play_media(url, item.text())
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

        self.setWindowTitle(f"播放: {title}")
        self.show_status_message(f"开始播放: {title}", 3000)

        # 强制刷新选中状态
        self.list_widget.clearSelection()
        item = self.list_widget.item(self.current_media_index)
        item.setSelected(True)
        self.list_widget.scrollToItem(item)

    def update_position(self):
        """Update the position slider and time labels"""
        if self.player.is_playing():
            # Get current position and duration in milliseconds
            position = self.player.get_time()
            duration = self.player.get_length()

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

    def on_item_double_clicked(self, item):
        if isinstance(item, FileItem):
            if item.file_type == 1:  # Directory
                self.path_history.append(self.current_path)
                self.back_btn.setEnabled(True)
                self.save_settings()
                self.load_files(item.fid)
            else:  # File
                self.current_media_index = self.list_widget.row(item)
                url = self.get_play_url(item.fid)
                if url:
                    self.play_media(url, item.text())

    def go_back(self):
        if self.path_history:
            prev_path = self.path_history.pop()
            self.save_settings()
            self.load_files(prev_path)
            self.back_btn.setEnabled(bool(self.path_history))

    def closeEvent(self, event):
        # 正常停止播放
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
