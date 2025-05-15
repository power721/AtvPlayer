import json
import os
import sys
import time
from datetime import datetime
from urllib.parse import unquote, quote

import requests
import vlc
from PyQt6.QtCore import Qt, QSize, QTimer, QSettings, QThread, QMetaObject, Q_ARG, pyqtSignal, QEvent
from PyQt6.QtGui import QIcon, QKeySequence, QAction, QColor, QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget, QLabel, QPushButton, QSlider, QHBoxLayout, QStyle, QSplitter, QLineEdit,
    QDialogButtonBox, QFormLayout, QDialog, QComboBox
)


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AList-TvBox 登录")
        self.setWindowIcon(QIcon.fromTheme("dialog-password"))

        layout = QFormLayout(self)

        self.server_input = QLineEdit()
        self.server_input.setPlaceholderText("http://localhost:4567")
        layout.addRow("服务器地址:", self.server_input)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("admin")
        layout.addRow("用户名:", self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("密码")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("密码:", self.password_input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        # 加载保存的服务器地址
        self.settings = QSettings("AtvPlayer", "Config")
        saved_server = self.settings.value("server_address", "")
        if saved_server:
            self.server_input.setText(saved_server)

        username = self.settings.value("username", "")
        if username:
            self.username_input.setText(username)


class SearchThread(QThread):
    search_complete = pyqtSignal(list)

    def __init__(self, api_base, token, keyword):
        super().__init__()
        self.api_url = f"{api_base}/api/telegram/search?wd={keyword}"
        self.keyword = keyword
        self.token = token

    def run(self):
        try:
            headers = {"x-access-token": self.token}
            response = requests.get(self.api_url, headers=headers)
            response.raise_for_status()
            self.search_complete.emit(response.json())
        except Exception as e:
            print(f"搜索出错: {str(e)}")
            self.search_complete.emit([])


def parse_path(path):
    return unquote(path.split('$')[1])


def encode_uri_component(text: str) -> str:
    """
    Equivalent to JavaScript's encodeURIComponent()
    Encodes all characters except: A-Z a-z 0-9 - _ . ! ~ * ' ( )
    """
    return quote(text, safe="!'()*-._~")


def format_time(ms):
    """Convert milliseconds to HH:MM:SS format"""
    seconds = int(ms / 1000)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def to_local_time(utc_string):
    utc_dt = datetime.fromisoformat(utc_string.replace('Z', '+00:00'))
    local_dt = utc_dt.astimezone()
    return local_dt.strftime("%c")


def find_icon_file():
    """查找图标文件位置"""
    possible_paths = [
        "app_icon.png",  # 开发环境路径
        "/usr/share/icons/app_icon.png",  # Linux系统路径
        ":/icons/app_icon.png"  # Qt资源系统路径
    ]

    for path in possible_paths:
        if path.startswith(":") or os.path.exists(path):
            return path
    return None


def get_share_type(tid: str) -> str:
    type_map = {
        '0': '📀',
        '5': '🚀',
        '7': '🌞',
        '3': '💾',
        '8': '📡',
        '9': '☁',
        '6': '🚁',
        '1': '🅿',
        '2': '⚡'
    }
    return type_map.get(tid, '')


def get_driver_type(tid: str) -> str:
    type_map = {
        '0': '阿里云盘',
        '5': '夸克网盘',
        '7': 'UC网盘',
        '3': '123云盘',
        '8': '115云盘',
        '9': '天翼云盘',
        '6': '移动云盘',
        '2': '迅雷云盘',
        '1': 'PikPak',
    }
    return type_map.get(tid, '')


def get_file_icon(file_type: int) -> QIcon:
    """Return appropriate icon based on file type"""
    if file_type == 1:  # Folder
        return QIcon.fromTheme("folder")
    elif file_type == 2:  # Video
        return QIcon.fromTheme("video-x-generic")
    elif file_type == 3:  # Audio
        return QIcon.fromTheme("audio-x-generic")
    elif file_type == 5:  # Image
        return QIcon.fromTheme("image-x-generic")
    else:  # Default file icon
        return QIcon.fromTheme("text-x-generic")


class SearchItem(QListWidgetItem):
    def __init__(self, item):
        name = item["name"]
        link = item["link"]
        tid = item["type"]
        ctime = to_local_time(item["time"])
        channel = item["channel"]
        type_name = get_share_type(tid)
        driver = get_driver_type(tid)
        text = f'{type_name} {name}'
        super().__init__(text)
        self.link = link
        self.setToolTip(f"""
                    <b>资源名称:</b> {name}<br/>
                    <b>网盘类型:</b> {driver}<br/>
                    <b>分享链接:</b> {link}<br/>
                    <b>分享时间:</b> {ctime}<br/>
                    <b>电报频道:</b> {channel}
                """)


class FileItem(QListWidgetItem):
    def __init__(self, file):
        name, fid, file_type, size = file["vod_name"], file["vod_id"], file["type"], file["vod_remarks"]
        if len(size) > 0:
            text = name + " (" + size + ")"
        else:
            text = name
        super().__init__(get_file_icon(file_type), text)
        self.fid = fid
        self.name = name
        self.file_type = file_type
        self.setToolTip(parse_path(fid))
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
    HOME_DIRECTORY = "1$/$1"
    media_finished_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.sub = ""
        self.settings = QSettings("AtvPlayer", "Config")
        self.api = self.settings.value("server_address", "")
        self.token = self.settings.value("token", "")
        # 初始化登录
        if not self.login():
            sys.exit(1)

        self.media_finished_signal.connect(self._handle_media_finished_async)

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
        self.was_playing = False
        self.media_duration = 0
        self.current_position = 0
        self.current_media_index = -1
        self.current_media_name = ""
        self.all_search_results = []

        # Initialize icons
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
        self.home_icon = QIcon.fromTheme("go-home")

        self.setWindowTitle("AList TvBox Player")
        self.resize(1920, 1080)
        self.showMaximized()
        self.set_app_icon()

        # Initialize UI and player
        self.init_ui()
        self.init_player()
        self.init_shortcuts()
        # self.init_menu()

        self.update_buttons()

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

    def set_app_icon(self):
        """设置应用图标"""
        icon_path = find_icon_file()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

    def get_sub_token(self):
        url = f"{self.api}/api/token"
        headers = {"x-access-token": self.token}
        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            self.show_status_message(f"登录失败: {response.text}", 5000)
            return False
        print(response.text)
        self.sub = response.text.split(",")[0]
        return True

    def login(self):
        """显示登录对话框并验证"""
        if self.token and self.get_sub_token():
            return True

        dialog = LoginDialog()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False

        server = dialog.server_input.text().strip()
        username = dialog.username_input.text().strip()
        password = dialog.password_input.text().strip()

        if not server or not username or not password:
            return False

        try:
            login_url = f"{server}/api/accounts/login"
            response = requests.post(login_url, json={
                "username": username,
                "password": password,
                "rememberMe": True
            }, timeout=10)

            response.raise_for_status()
            data = response.json()

            # 保存登录信息
            self.settings = QSettings("AtvPlayer", "Config")
            self.settings.setValue("server_address", server)
            self.settings.setValue("username", username)
            self.settings.setValue("token", data.get("token"))
            self.settings.sync()

            self.api = server
            self.token = data.get("token")
            self.show_status_message("登录成功")
            return True

        except Exception as e:
            self.show_status_message(f"登录失败: {str(e)}", 5000)
            return False

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

        # 时间提示标签（初始隐藏）
        self.time_tooltip = QLabel(self)
        self.time_tooltip.setStyleSheet("""
                QLabel {
                    background: rgba(30, 30, 30, 180);
                    color: white;
                    padding: 3px 6px;
                    border-radius: 4px;
                    font: 10pt "Arial";
                }
            """)
        self.time_tooltip.hide()
        self.time_tooltip.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)

        # Progress slider (center)
        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.sliderMoved.connect(self.seek_position)
        self.progress_slider.mousePressEvent = self.progress_bar_click
        self.progress_slider.sliderPressed.connect(self.pause_for_seek)
        self.progress_slider.sliderReleased.connect(self.resume_after_seek)
        self.progress_slider.setMouseTracking(True)  # 必须启用！
        self.progress_slider.installEventFilter(self)  # 安装事件过滤器
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

        # 中间状态消息区域
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("""
               QLabel {
                   color: #666;
                   font-size: 12px;
                   qproperty-alignment: AlignCenter;
               }
           """)
        self.status_label.setMinimumWidth(200)
        button_layout.addWidget(self.status_label, stretch=1)

        # Volume controls
        volume_container = QWidget()
        volume_layout = QHBoxLayout()
        volume_layout.setContentsMargins(0, 0, 0, 0)
        volume_layout.setSpacing(5)

        volume_layout.addWidget(QLabel("音量:"))

        # 音量滑块
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(self.settings.value("volume", 70)))
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

        # 修改右侧布局 - 添加搜索区域
        self.right_widget = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)

        # 1. 后退按钮和主目录按钮容器
        nav_container = QWidget()
        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(5)

        # 后退按钮 (modified to be inside the container)
        self.back_btn = QPushButton(self.prev_icon, "后退")
        self.back_btn.clicked.connect(self.go_back)
        self.back_btn.setEnabled(bool(self.path_history))
        # self.back_btn.setToolTip("返回上一级目录")
        nav_layout.addWidget(self.back_btn)

        # 主目录按钮
        self.home_btn = QPushButton(self.home_icon, "主目录")
        self.home_btn.clicked.connect(self.go_home)
        # self.home_btn.setToolTip("返回主目录")
        nav_layout.addWidget(self.home_btn)

        nav_container.setLayout(nav_layout)
        right_layout.addWidget(nav_container)

        # 2. 文件列表
        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(24, 24))
        self.list_widget.itemClicked.connect(self.on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        right_layout.addWidget(self.list_widget, stretch=1)  # 文件列表占据主要空间

        # 3. 新增搜索区域
        search_container = QWidget()
        search_layout = QVBoxLayout()
        search_layout.setContentsMargins(0, 5, 0, 0)

        # 搜索框和搜索按钮
        search_box = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.search_input.setPlaceholderText("输入关键词搜索...")
        self.search_input.returnPressed.connect(self.do_remote_search)
        search_box.addWidget(self.search_input)

        # 添加类型下拉框
        self.type_combo = QComboBox()
        self.type_combo.addItem("全部类型", "")
        self.type_combo.addItem("📀 阿里云盘", "0")
        self.type_combo.addItem("🚀 夸克网盘", "5")
        self.type_combo.addItem("🌞 UC网盘", "7")
        self.type_combo.addItem("💾 123云盘", "3")
        self.type_combo.addItem("📡 115云盘", "8")
        self.type_combo.addItem("☁ 天翼云盘", "9")
        self.type_combo.addItem("🚁 移动云盘", "6")
        self.type_combo.addItem("⚡ 迅雷云盘", "2")
        self.type_combo.addItem("🅿 PikPak", "1")
        self.type_combo.currentIndexChanged.connect(self.on_type_changed)  # 添加类型变化事件
        search_box.addWidget(self.type_combo)

        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self.do_remote_search)
        search_box.addWidget(self.search_btn)

        search_layout.addLayout(search_box)

        # 搜索结果列表
        self.search_results = QListWidget()
        self.search_results.setIconSize(QSize(24, 24))
        self.search_results.itemClicked.connect(self.on_search_item_clicked)
        self.search_results.setVisible(False)
        search_layout.addWidget(self.search_results)

        search_container.setLayout(search_layout)
        right_layout.addWidget(search_container)

        self.right_widget.setLayout(right_layout)

        # Add both sides to splitter
        self.main_splitter = main_splitter  # Make splitter accessible for toggling
        self.main_splitter.addWidget(left_widget)
        self.main_splitter.addWidget(self.right_widget)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 1)

        # Set central widget
        self.setCentralWidget(main_splitter)

        self.video_widget.setMouseTracking(True)
        self.video_widget.installEventFilter(self)

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

    def escape(self):
        self.search_input.clearFocus()
        self.exit_fullscreen()

    def exit_fullscreen(self):
        if not self.is_fullscreen:
            return
        self.is_fullscreen = False
        self.showNormal()
        self.menuBar().show()

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

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def show_status_message(self, message, timeout=3000, print_message=True):
        if print_message:
            print(f"[INFO] {message}")

        if hasattr(self, 'status_label'):
            self.status_label.setText(message)

            # 设置定时清除消息
            if hasattr(self, 'status_timer'):
                self.status_timer.stop()

            if timeout > 0:
                self.status_timer = QTimer()
                self.status_timer.timeout.connect(lambda: self.status_label.setText(""))
                self.status_timer.start(timeout)

    def init_player(self):
        try:
            # 尝试从系统路径加载
            self.instance = vlc.Instance()
            if not self.instance:
                raise RuntimeError("无法初始化VLC实例")

            self.player = self.instance.media_player_new()
        except Exception as e:
            print(f"VLC初始化失败: {str(e)}")
            self.fallback_to_system_vlc()

        # Set video output to our widget
        if sys.platform.startswith('linux'):  # for Linux using the X Server
            self.player.set_xwindow((int(self.video_widget.winId())))
        elif sys.platform == "win32":  # for Windows
            self.player.set_hwnd(int(self.video_widget.winId()))
        elif sys.platform == "darwin":  # for MacOS
            self.player.set_nsobject(int(self.video_widget.winId()))
        self.player.event_manager().event_attach(
            vlc.EventType.MediaPlayerEndReached,
            self._vlc_callback_wrapper  # 改用包装器
        )
        self.set_volume(self.volume_slider.value())  # Set from saved value

    def fallback_to_system_vlc(self):
        """尝试从常见路径加载VLC"""
        vlc_paths = {
            'win32': [
                r'C:\Program Files\VideoLAN\VLC',
                r'C:\Program Files (x86)\VideoLAN\VLC'
            ],
            'darwin': [
                '/Applications/VLC.app/Contents/MacOS/lib',
                '/usr/local/lib'
            ],
            'linux': [
                '/usr/lib',
                '/usr/local/lib'
            ]
        }

        for path in vlc_paths.get(sys.platform, []):
            try:
                os.environ['VLC_PLUGIN_PATH'] = path
                self.instance = vlc.Instance()
                if self.instance:
                    self.player = self.instance.media_player_new()
                    print(f"成功从 {path} 加载VLC")
                    return
            except Exception:
                continue

        raise RuntimeError("无法加载VLC，请确保已安装VLC媒体播放器")

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
        # Play/Pause toggle with Space
        self.play_action = QAction(self)
        self.play_action.setShortcut(QKeySequence(Qt.Key.Key_Space))
        self.play_action.triggered.connect(self.play_pause)
        self.addAction(self.play_action)

        # Escape
        self.stop_action = QAction(self)
        self.stop_action.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        self.stop_action.triggered.connect(self.escape)
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

        # 添加Ctrl+Right快进30秒
        self.fast_forward_action = QAction(self)
        self.fast_forward_action.setShortcut(QKeySequence("Ctrl+Right"))
        self.fast_forward_action.triggered.connect(lambda: self.seek_relative(30))
        self.addAction(self.fast_forward_action)

        # 对称添加快退快捷键
        self.rewind_action = QAction(self)
        self.rewind_action.setShortcut(QKeySequence("Ctrl+Left"))
        self.rewind_action.triggered.connect(lambda: self.seek_relative(-30))
        self.addAction(self.rewind_action)

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

        # 添加搜索快捷键
        self.search_action = QAction(self)
        self.search_action.setShortcut(QKeySequence("Ctrl+F"))
        self.search_action.triggered.connect(self.focus_search_input)
        self.addAction(self.search_action)

    def focus_search_input(self):
        """聚焦到搜索框"""
        self.search_input.setFocus()

    def update_buttons(self):
        """Update button states based on player status"""
        # self.is_playing = self.player.is_playing()
        if self.is_playing:
            self.play_btn.setIcon(self.pause_icon)
        else:
            self.play_btn.setIcon(self.play_icon)
        self.stop_btn.setEnabled(bool(self.player.get_media()))

        has_items = self.list_widget.count() > 0
        self.prev_btn.setEnabled(has_items and self.current_media_index > 0)
        self.next_btn.setEnabled(has_items and self.current_media_index < self.list_widget.count() - 1)

    def eventFilter(self, obj, event):
        if obj == self.video_widget and event.type() == QEvent.Type.MouseMove:
            if self.player.is_playing():
                self.set_mouse_visibility(True)
                self.mouse_timer.start(3000)
        # 只处理进度条相关事件
        if obj == self.progress_slider:
            if event.type() == QEvent.Type.MouseMove:
                self.show_time_tooltip(event)
            elif event.type() == QEvent.Type.Leave:
                self.time_tooltip.hide()
        return super().eventFilter(obj, event)

    def show_time_tooltip(self, event):
        """显示时间提示框"""
        if not self.player.get_media():
            return

        # 计算鼠标位置对应的时间
        mouse_x = event.position().x()
        percent = mouse_x / self.progress_slider.width()
        time_pos = int(self.player.get_length() * percent)

        # 更新提示框内容和位置
        self.time_tooltip.setText(format_time(time_pos))

        # 计算提示框位置（跟随鼠标）
        pos = self.progress_slider.mapToGlobal(event.position().toPoint())
        self.time_tooltip.move(pos.x() - 20, pos.y() - 30)
        self.time_tooltip.show()

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
                self.show_status_message(f"暂停播放: {self.current_media_name}")
            else:
                self.player.play()
                self.is_playing = True
                self.set_mouse_visibility(False)  # 播放时隐藏鼠标
                self.show_status_message(f"恢复播放: {self.current_media_name}")
        self.update_buttons()

    def stop(self):
        """Stop playback"""
        self.player.stop()
        media = self.player.get_media()
        if media:
            media.release()
            self.player.set_media(None)  # 清空媒体引用
            self.show_status_message(f"停止播放: {self.current_media_name}")
        self.is_playing = False
        self.progress_container.setVisible(False)
        self.set_mouse_visibility(True)  # 停止时显示鼠标
        self.setWindowTitle("AList TvBox Player")
        # 清除高亮状态
        item = self.list_widget.item(self.current_media_index)
        if isinstance(item, FileItem):
            item.set_playing(False)
        self.exit_fullscreen()
        self.update_buttons()

    def add_file_item(self, file):
        """Add a file or folder item with appropriate icon"""
        item = FileItem(file)
        item.set_playing(self.last_played_fid == file["vod_id"])
        self.list_widget.addItem(item)

    def load_files(self, fid):
        self.show_status_message(f"加载目录: {parse_path(fid)}")
        QApplication.processEvents()
        self.home_btn.setEnabled(fid != self.HOME_DIRECTORY)

        url = f"{self.api}/vod/{self.sub}?ac=web&t={fid}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            files = response.json().get("list", [])

            self.list_widget.clear()
            if not files:
                self.show_status_message("没有文件")
                return

            for file in files:
                if file["type"] != 9:
                    self.add_file_item(file)

            self.current_path = fid
            self.save_settings()

        except Exception as e:
            self.show_status_message(f"加载目录错误: {str(e)}", 5000)

    def do_remote_search(self):
        """执行远程搜索"""
        keyword = self.search_input.text().strip()

        self.show_status_message(f"正在搜索: {keyword}...")
        self.search_results.clear()

        # 使用线程避免阻塞UI
        self.search_thread = SearchThread(self.api, self.token, keyword)
        self.search_thread.search_complete.connect(self.filter_search_results)
        self.search_thread.start()

    def on_type_changed(self):
        """当类型下拉框选项变化时，重新筛选结果"""
        if hasattr(self, 'all_search_results') and self.all_search_results:
            self.filter_search_results(self.all_search_results)

    def filter_search_results(self, all_results):
        """本地筛选搜索结果"""
        if not all_results:
            self.show_status_message("未找到匹配结果")
            return

        # 保存所有结果供后续筛选使用
        self.all_search_results = all_results

        # 获取当前选择的类型
        selected_type = self.type_combo.currentData()

        # 筛选结果
        filtered_results = []
        if selected_type:  # 如果选择了特定类型
            filtered_results = [item for item in all_results if item["type"] == selected_type]
        else:  # 显示全部结果
            filtered_results = all_results

        # 显示筛选后的结果
        self.display_search_results(filtered_results)

    def display_search_results(self, results):
        """显示搜索结果"""
        self.search_results.clear()

        if not results:
            self.show_status_message("未找到匹配结果")
            return

        for item in results:
            file_item = SearchItem(item)
            self.search_results.addItem(file_item)

        selected_type = self.type_combo.currentText()
        type_info = f" ({selected_type})" if selected_type != "全部类型" else ""
        self.show_status_message(f"显示 {len(results)} 个结果{type_info}", 5000)
        self.search_results.setVisible(True)

    def on_search_item_clicked(self, item):
        """处理搜索结果点击事件"""
        if isinstance(item, SearchItem):
            url = f"{self.api}/api/share-link"
            try:
                headers = {"x-access-token": self.token}
                data = {"link": item.link}
                response = requests.post(url, json=data, headers=headers)
                response.raise_for_status()
                # self.path_history.append(self.current_path)
                self.back_btn.setEnabled(True)
                self.load_files(f"1${encode_uri_component(response.text)}$1")
            except Exception as e:
                self.show_status_message(f"添加分享失败: {str(e)}", 5000)

    def get_play_url(self, fid):
        url = f"{self.api}/vod/{self.sub}?ac=web&ids={fid}"
        try:
            self.show_status_message("获取播放地址")
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
        if self.list_widget.count() > 0:
            # Find next playable item
            next_index = self.find_next_playable_item(self.current_media_index + 1)
            print(f'next index: {next_index}')
            if next_index >= 0:
                self.play_item_at_index(next_index)
            else:
                self.stop()
                self.show_status_message(f"播放完毕: {self.current_media_name}")
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
            if self.current_media_index > -1:
                self.play_item_at_index(self.current_media_index)
                return

            # 尝试自动选择第一个可播放文件
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if isinstance(item, FileItem) and item.file_type != 1:
                    self.list_widget.setCurrentItem(item)
                    self.current_media_index = i
                    url = self.get_play_url(item.fid)
                    if url:
                        return self.play_media(url, item.name)

            self.show_status_message("找不到可播放文件")
            return

        item = selected_items[0]  # 获取第一个选中项
        if isinstance(item, FileItem) and item.file_type != 1:  # 确保是文件
            self.current_media_index = self.list_widget.row(item)
            url = self.get_play_url(item.fid)
            if url:
                self.play_media(url, item.name)
        else:
            self.show_status_message("无媒体文件")

    def play_next(self):
        """播放下一个有效视频文件"""
        if self.list_widget.count() == 0:
            return

        next_index = self.find_playable_item(self.current_media_index + 1)
        if next_index >= 0:
            self.play_item_at_index(next_index)
        else:
            self.show_status_message("已是最后一个视频")

    def play_previous(self):
        """播放上一个有效视频文件"""
        if self.list_widget.count() == 0:
            return

        prev_index = self.find_playable_item(self.current_media_index - 1, reverse=True)
        if prev_index >= 0:
            self.play_item_at_index(prev_index)
        else:
            self.show_status_message("已是第一个视频")

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
        self.player.stop()
        if media := self.player.get_media():
            media.release()

        media = self.instance.media_new(url)
        self.player.set_media(media)
        self.player.play()
        self.is_playing = True

        # UI 更新
        self.progress_container.setVisible(True)
        self.set_mouse_visibility(False)
        self.update_buttons()

        self.current_media_name = title
        self.setWindowTitle(title)
        self.show_status_message(f"开始播放: {title}")

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
            position = self.player.get_time()
            duration = self.player.get_length()

            # 每5秒保存一次播放进度
            if int(time.time()) % 5 == 0:
                self.save_playback_state()

            if duration > 0:
                self.progress_slider.setValue(int(1000 * position / duration))
                self.current_time_label.setText(format_time(position))
                self.duration_label.setText(format_time(duration))

    def progress_bar_click(self, event):
        """点击进度条任意位置跳转"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.player.get_media():
                # 计算点击位置对应的百分比
                percent = event.position().x() / self.progress_slider.width()
                target_pos = int(self.player.get_length() * percent)

                # 跳转到指定位置
                self.player.set_time(target_pos)

                # 更新进度条显示
                self.progress_slider.setValue(int(percent * 1000))

                # 显示跳转提示
                self.show_status_message(f"跳转到: {format_time(target_pos)}", 1000)

    def seek_position(self, value):
        """Seek to a specific position in the media"""
        if self.player.get_media():
            duration = self.player.get_length()
            position = int(duration * value / 1000)
            self.player.set_time(position)

    def seek_relative(self, seconds):
        """Seek forward or backward by specified seconds"""
        if self.player.get_media():
            direction = "前进" if seconds > 0 else "后退"
            self.show_status_message(f"{direction} {abs(seconds)}秒", 1000)
            current_pos = self.player.get_time()
            new_pos = current_pos + (seconds * 1000)
            duration = self.player.get_length()

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
                self.stop()
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
            self.home_btn.setEnabled(self.current_path != self.HOME_DIRECTORY)

    def go_home(self):
        """Return to the home directory"""
        if self.current_path != self.HOME_DIRECTORY:
            self.path_history.append(self.current_path)
            self.back_btn.setEnabled(True)
            self.load_files(self.HOME_DIRECTORY)

    def closeEvent(self, event):
        # 正常停止播放
        if hasattr(self, 'player') and self.player.is_playing():
            self.save_playback_state()
        if hasattr(self, 'player'):
            self.player.stop()
            if media := self.player.get_media():
                media.release()
            self.player.release()

        self.instance.release()
        # 确保设置已写入磁盘
        self.settings.sync()
        event.accept()


if __name__ == "__main__":
    app = QApplication([])
    window = AtvPlayer()
    window.show()
    app.exec()
