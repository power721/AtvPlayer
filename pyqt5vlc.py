import requests
import vlc
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget, QLabel, QStatusBar, QToolBar,
    QPushButton, QSlider, QHBoxLayout
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QKeySequence, QAction


class FileItem(QListWidgetItem):
    def __init__(self, name, fid, file_type):
        super().__init__(name)
        self.fid = fid
        self.file_type = file_type


class AtvPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.api = 'http://localhost:4567/vod/Harold'
        self.current_path = "1$/$1"
        self.path_history = []
        self.is_playing = False

        self.setWindowTitle("AList TvBox Player")
        self.resize(800, 600)

        # Initialize UI and player
        self.init_ui()
        self.init_player()
        self.init_shortcuts()

        # Load initial files
        self.load_files(self.current_path)

    def init_ui(self):
        # Main toolbar
        toolbar = QToolBar("Main Controls")
        self.addToolBar(toolbar)

        # Navigation controls
        self.back_btn = QPushButton(QIcon(), "Back")
        self.back_btn.clicked.connect(self.go_back)
        self.back_btn.setEnabled(False)
        toolbar.addWidget(self.back_btn)

        # Media controls
        self.play_btn = QPushButton(QIcon(), "Play")
        self.play_btn.clicked.connect(self.play_pause)
        toolbar.addWidget(self.play_btn)

        self.stop_btn = QPushButton(QIcon(), "Stop")
        self.stop_btn.clicked.connect(self.stop)
        toolbar.addWidget(self.stop_btn)

        # Volume controls
        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Volume:"))

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.valueChanged.connect(self.set_volume)
        self.volume_slider.setFixedWidth(100)
        toolbar.addWidget(self.volume_slider)

        # File list
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Main layout
        layout = QVBoxLayout()
        layout.addWidget(self.list_widget)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Update button states
        self.update_buttons()

    def init_player(self):
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()
        self.set_volume(70)  # Default volume


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

    def update_buttons(self):
        """Update button states based on player status"""
        self.play_btn.setText("Pause" if self.is_playing else "Play")
        self.stop_btn.setEnabled(self.is_playing)

    def set_volume(self, volume):
        """Set volume (0-100)"""
        if 0 <= volume <= 100:
            self.player.audio_set_volume(volume)
            self.status_bar.showMessage(f"Volume: {volume}%", 2000)

    def volume_up(self):
        """Increase volume by 5"""
        current = self.player.audio_get_volume()
        self.set_volume(min(100, current + 5))

    def volume_down(self):
        """Decrease volume by 5"""
        current = self.player.audio_get_volume()
        self.set_volume(max(0, current - 5))

    def play_pause(self):
        """Toggle play/pause"""
        if self.player.get_media():
            if self.player.is_playing():
                self.player.pause()
                self.is_playing = False
            else:
                self.player.play()
                self.is_playing = True
            self.update_buttons()

    def stop(self):
        """Stop playback"""
        self.player.stop()
        self.is_playing = False
        self.setWindowTitle("AList TvBox Player")
        self.update_buttons()
        self.status_bar.showMessage("Playback stopped", 2000)

    def add_file_item(self, name, fid, file_type):
        item = FileItem(name, fid, file_type)
        self.list_widget.addItem(item)

    def load_files(self, path):
        self.status_bar.showMessage("Loading...")
        QApplication.processEvents()  # Update UI

        url = f"{self.api}?ac=web&t={path}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            files = response.json().get("list", [])

            self.list_widget.clear()
            if not files:
                self.status_bar.showMessage("No files found", 3000)
                return

            for file in files:
                if file["type"] != 9:
                    self.add_file_item(file["vod_name"], file["vod_id"], file["type"])

            self.current_path = path
            self.status_bar.showMessage(f"Loaded: {path}", 3000)

        except requests.RequestException as e:
            self.status_bar.showMessage(f"Error loading files: {str(e)}", 5000)
        except Exception as e:
            self.status_bar.showMessage(f"Error: {str(e)}", 5000)

    def get_play_url(self, fid):
        url = f"{self.api}?ac=web&ids={fid}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            files = response.json().get("list", [])
            if files:
                return files[0]["vod_play_url"]
        except Exception as e:
            self.status_bar.showMessage(f"Error getting URL: {str(e)}", 5000)
        return None

    def play_media(self, url, title=None):
        """Play media with optional title"""
        media = self.instance.media_new(url)
        self.player.set_media(media)
        self.player.play()
        self.is_playing = True
        self.update_buttons()

        if title:
            self.setWindowTitle(f"Now Playing: {title}")
            self.status_bar.showMessage(f"Playing: {title}", 3000)

    def on_item_double_clicked(self, item):
        if isinstance(item, FileItem):
            if item.file_type == 1:  # Directory
                self.path_history.append(self.current_path)
                self.back_btn.setEnabled(True)
                self.load_files(item.fid)
            else:  # File
                url = self.get_play_url(item.fid)
                if url:
                    self.play_media(url, item.text())

    def go_back(self):
        if self.path_history:
            prev_path = self.path_history.pop()
            self.load_files(prev_path)
            if not self.path_history:
                self.back_btn.setEnabled(False)

    def closeEvent(self, event):
        if hasattr(self, 'player'):
            self.player.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication([])
    window = AtvPlayer()
    window.show()
    app.exec()