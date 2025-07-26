import sys
import os
import time
from pathlib import Path
import qdarktheme
from packaging import version
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QLineEdit, 
                            QPushButton, QProgressBar, QFileDialog, QDialog, QDialogButtonBox)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QSettings, QTimer, QUrl
from PyQt6.QtGui import QIcon, QPixmap, QCursor, QDesktopServices
import requests
from mutagen.mp4 import MP4, MP4Cover

DEFAULT_COOKIES = "PHPSESSID=qse7m9ski4k1sqiefelojpv5pq"
WINDOW_WIDTH = 600
WINDOW_HEIGHT = 180
LABEL_WIDTH = 100
BUTTON_WIDTH = 100
REQUEST_TIMEOUT = 30

class TrackInfoFetcher(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, url, cookies):
        super().__init__()
        self.url = url
        self.cookies = cookies
                    
    def run(self):
        try:
            headers = {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                "Origin": "https://scloudplaylistdownloadermp3.com",
                "Referer": "https://scloudplaylistdownloadermp3.com/",
                "Cookie": self.cookies
            }
            
            data = {"url": self.url}
            response = requests.post(
                "https://scloudplaylistdownloadermp3.com/api/scinfo.php", 
                data=data, 
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()
            self.finished.emit(result)
        except requests.exceptions.RequestException as e:
            self.error.emit(f"Network error: {str(e)}")
        except Exception as e:
            self.error.emit(str(e))

class DownloaderWorker(QThread):
    progress = pyqtSignal(int)
    progress_status = pyqtSignal(str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, track_info, output_dir):
        super().__init__()
        self.track_info = track_info
        self.output_dir = output_dir

    def _create_safe_filename(self, track_info):
        artist = track_info.get('artist', 'Unknown')
        name = track_info.get('name', 'Unknown')
        filename = f"{artist} - {name}.m4a"
        return "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()

    def _format_file_size(self, size_bytes):
        if size_bytes == 0:
            return "0B"
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.1f}{size_names[i]}"

    def _download_file(self, url, filepath):
        try:
            response = requests.get(url, stream=True, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            
            file_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            start_time = time.time()
            last_time = start_time
            last_downloaded = 0
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        current_time = time.time()
                        
                        if current_time - last_time >= 0.5 or downloaded == file_size:
                            if file_size > 0:
                                progress = 10 + int((downloaded / file_size) * 70)
                                self.progress.emit(progress)
                                
                                time_diff = current_time - last_time
                                if time_diff > 0:
                                    bytes_diff = downloaded - last_downloaded
                                    speed_bps = bytes_diff / time_diff
                                    speed_str = f"{self._format_file_size(speed_bps)}/s"
                                    
                                    downloaded_str = self._format_file_size(downloaded)
                                    total_str = self._format_file_size(file_size)
                                    status = f"Downloading... {downloaded_str} / {total_str} ({speed_str})"
                                    self.progress_status.emit(status)
                                    
                                    last_time = current_time
                                    last_downloaded = downloaded
            
            return True
        except requests.exceptions.RequestException as e:
            raise Exception(f"Download failed: {str(e)}")

    def _add_metadata(self, filepath, track_info):
        try:
            audio = MP4(filepath)
            
            if track_info.get('artist'):
                audio['\xa9ART'] = [track_info['artist']]
            if track_info.get('date'):
                audio['\xa9day'] = [track_info['date']]
            
            self.progress.emit(90)
            
            if track_info.get('thumb'):
                try:
                    thumb_response = requests.get(track_info['thumb'], timeout=REQUEST_TIMEOUT)
                    thumb_response.raise_for_status()
                    thumb_data = thumb_response.content
                    
                    if thumb_data:
                        cover_format = MP4Cover.FORMAT_JPEG if thumb_data.startswith(b'\xff\xd8') else MP4Cover.FORMAT_PNG
                        audio['covr'] = [MP4Cover(thumb_data, imageformat=cover_format)]
                except requests.exceptions.RequestException:
                    pass
            
            audio.save()
            
        except Exception as e:
            raise Exception(f"Failed to add metadata: {str(e)}")

    def run(self):
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            
            filename = self._create_safe_filename(self.track_info)
            filepath = os.path.join(self.output_dir, filename)
            
            self.progress.emit(10)
            self.progress_status.emit("Preparing download...")
            
            if not self.track_info.get('dlink_m4a'):
                raise Exception("No download link available")
                
            self._download_file(self.track_info['dlink_m4a'], filepath)
            self.progress.emit(80)
            self.progress_status.emit("Adding metadata...")
            
            self._add_metadata(filepath, self.track_info)
            self.progress.emit(100)
            self.progress_status.emit("Download completed!")
            
            self.finished.emit(f"Downloaded: {os.path.basename(filepath)}")
            
        except Exception as e:
            self.error.emit(f"Error: {str(e)}")

class UpdateDialog(QDialog):
    def __init__(self, current_version, new_version, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update Now")
        self.setFixedWidth(400)
        self.setModal(True)

        layout = QVBoxLayout()

        message = QLabel(f"SoundCloud Go+ Downloader v{new_version} Available!")
        message.setWordWrap(True)
        layout.addWidget(message)

        button_box = QDialogButtonBox()
        self.update_button = QPushButton("Check")
        self.update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button = QPushButton("Later")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        
        button_box.addButton(self.update_button, QDialogButtonBox.ButtonRole.AcceptRole)
        button_box.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        
        layout.addWidget(button_box)

        self.setLayout(layout)

        self.update_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

class SoundCloudGoPlusDownloaderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_version = "1.1"
        self.settings = QSettings('SoundCloudGoPlusDownloader', 'Settings')
        self.setWindowTitle("SoundCloud Go+ Downloader")
        
        self._setup_window()
        self._setup_default_dir()
        
        self.track_info = None
        self.fetcher = None
        self.worker = None
        
        self.init_ui()
        self._connect_signals()
        self.load_settings()
        
        self.check_for_updates = self.settings.value('check_for_updates', True, type=bool)
        if self.check_for_updates:
            QTimer.singleShot(0, self.check_updates)

    def check_updates(self):
        try:
            response = requests.get("https://raw.githubusercontent.com/afkarxyz/SoundCloudGoPlusDownloader/refs/heads/main/version.json", timeout=10)
            if response.status_code == 200:
                data = response.json()
                new_version = data.get("version")
                
                if new_version and version.parse(new_version) > version.parse(self.current_version):
                    dialog = UpdateDialog(self.current_version, new_version, self)
                    result = dialog.exec()
                    
                    if result == QDialog.DialogCode.Accepted:
                        QDesktopServices.openUrl(QUrl("https://github.com/afkarxyz/SoundCloudGoPlusDownloader/releases"))
                        
        except Exception as e:
            print(f"Error checking for updates: {e}")
        
    def _setup_window(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.setFixedWidth(WINDOW_WIDTH)
        self.setFixedHeight(WINDOW_HEIGHT)
        
    def _setup_default_dir(self):
        self.default_music_dir = str(Path.home() / "Music")
        if not os.path.exists(self.default_music_dir):
            os.makedirs(self.default_music_dir)
            
    def _connect_signals(self):
        self.url_input.textChanged.connect(self.validate_url)
        self.cookies_input.textChanged.connect(
            lambda x: self.settings.setValue('cookies', x))
        self.dir_input.textChanged.connect(
            lambda x: self.settings.setValue('output_dir', x))
        
    def load_settings(self):
        cookies = self.settings.value('cookies', DEFAULT_COOKIES)
        output_dir = self.settings.value('output_dir', self.default_music_dir)
        
        self.cookies_input.setText(cookies)
        self.dir_input.setText(output_dir)

    def _create_input_section(self):
        self.input_widget = QWidget()
        input_layout = QVBoxLayout(self.input_widget)
        input_layout.setSpacing(15)

        url_layout = QHBoxLayout()
        url_label = QLabel("SoundCloud URL:")
        url_label.setFixedWidth(LABEL_WIDTH)
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter SoundCloud URL")
        self.url_input.setClearButtonEnabled(True)
        
        self.fetch_button = QPushButton("Fetch")
        self.fetch_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.fetch_button.setFixedWidth(BUTTON_WIDTH)
        self.fetch_button.setEnabled(False)
        self.fetch_button.clicked.connect(self.fetch_track_info)
        
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.fetch_button)
        input_layout.addLayout(url_layout)

        dir_layout = QHBoxLayout()
        dir_label = QLabel("Output Directory:")
        dir_label.setFixedWidth(LABEL_WIDTH)
        self.dir_input = QLineEdit(self.default_music_dir)
        self.dir_button = QPushButton("Browse")
        self.dir_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.dir_button.setFixedWidth(BUTTON_WIDTH)
        self.dir_button.clicked.connect(self.select_directory)
        
        dir_layout.addWidget(dir_label)
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(self.dir_button)
        input_layout.addLayout(dir_layout)

        cookies_layout = QHBoxLayout()
        cookies_label = QLabel("Cookies:")
        cookies_label.setFixedWidth(LABEL_WIDTH)
        
        self.cookies_input = QLineEdit()
        self.cookies_input.setPlaceholderText(DEFAULT_COOKIES)
        self.cookies_input.setText(DEFAULT_COOKIES)
        self.cookies_input.setClearButtonEnabled(True)
        
        self.reset_cookies_button = QPushButton("Reset")
        self.reset_cookies_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.reset_cookies_button.setFixedWidth(BUTTON_WIDTH)
        self.reset_cookies_button.clicked.connect(self.reset_cookies)
        
        cookies_layout.addWidget(cookies_label)
        cookies_layout.addWidget(self.cookies_input)
        cookies_layout.addWidget(self.reset_cookies_button)
        input_layout.addLayout(cookies_layout)
        
        input_layout.addStretch()
        return self.input_widget

    def _create_track_display_section(self):
        self.track_widget = QWidget()
        self.track_widget.hide()
        track_layout = QHBoxLayout(self.track_widget)
        track_layout.setContentsMargins(0, 0, 0, 0)
        track_layout.setSpacing(10)

        cover_container = QWidget()
        cover_layout = QVBoxLayout(cover_container)
        cover_layout.setContentsMargins(0, 0, 0, 0)
        cover_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(100, 100)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet("border: 1px solid gray;")
        cover_layout.addWidget(self.cover_label)
        track_layout.addWidget(cover_container)

        track_details_container = QWidget()
        track_details_layout = QVBoxLayout(track_details_container)
        track_details_layout.setContentsMargins(0, 0, 0, 0)
        track_details_layout.setSpacing(2)
        track_details_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        label_style = "font-size: 12px;"
        title_style = "font-size: 13px; font-weight: bold;"
        min_width = 400

        self.title_label = QLabel()
        self.title_label.setStyleSheet(title_style)
        self.title_label.setWordWrap(True)
        self.title_label.setMinimumWidth(min_width)
        
        for attr_name in ['artist_label', 'duration_label', 'date_label']:
            label = QLabel()
            label.setStyleSheet(label_style)
            label.setWordWrap(True)
            label.setMinimumWidth(min_width)
            label.setTextFormat(Qt.TextFormat.RichText)
            setattr(self, attr_name, label)
            track_details_layout.addWidget(label)

        track_details_layout.insertWidget(0, self.title_label)
        track_layout.addWidget(track_details_container, stretch=1)
        track_layout.addStretch()

        return self.track_widget

    def _create_control_buttons(self):
        button_configs = [
            ('download_button', 'Download', self.button_clicked),
            ('cancel_button', 'Cancel', self.cancel_clicked),
            ('open_button', 'Open', self.open_output_directory)
        ]
        
        for attr_name, text, handler in button_configs:
            button = QPushButton(text)
            button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            button.setFixedWidth(BUTTON_WIDTH)
            button.clicked.connect(handler)
            button.hide()
            setattr(self, attr_name, button)

        download_layout = QHBoxLayout()
        download_layout.addStretch()
        download_layout.addWidget(self.open_button)
        download_layout.addWidget(self.download_button)
        download_layout.addWidget(self.cancel_button)
        download_layout.addStretch()
        
        return download_layout

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setContentsMargins(10, 10, 10, 10)

        self.main_layout.addWidget(self._create_input_section())
        self.main_layout.addWidget(self._create_track_display_section())
        self.main_layout.addLayout(self._create_control_buttons())

        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        self.main_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.main_layout.addWidget(self.status_label)

    def _reset_ui_state(self):
        self.progress_bar.hide()
        self.progress_bar.setValue(0)
        self.download_button.hide()
        self.cancel_button.hide()
        self.open_button.hide()
        self.track_widget.hide()
        self.input_widget.show()
        self.fetch_button.setEnabled(True)
        self.setFixedHeight(WINDOW_HEIGHT)

    def validate_url(self, url):
        url = url.strip()
        
        self.fetch_button.setEnabled(False)
        
        if not url:
            self.status_label.clear()
            return
            
        if "soundcloud.com/" not in url:
            self.status_label.setText("Please enter a valid SoundCloud URL")
            return
            
        self.fetch_button.setEnabled(True)
        self.status_label.clear()

    def fetch_track_info(self):
        url = self.url_input.text().strip()
        cookies = self.cookies_input.text().strip()
        
        if not url:
            self.status_label.setText("Please enter a SoundCloud URL")
            return

        self.fetch_button.setEnabled(False)
        self.status_label.setText("Fetching track information...")
        
        if self.fetcher:
            self.fetcher.deleteLater()
            
        self.fetcher = TrackInfoFetcher(url, cookies)
        self.fetcher.finished.connect(self.handle_track_info)
        self.fetcher.error.connect(self.handle_fetch_error)
        self.fetcher.start()

    def handle_track_info(self, info):
        self.track_info = info
        self.fetch_button.setEnabled(True)
        
        self.title_label.setText(info.get('name', 'Unknown'))
        self.artist_label.setText(f"<b>Artist:</b> {info.get('artist', 'Unknown')}")
        self.duration_label.setText(f"<b>Duration:</b> {info.get('duration', 'Unknown')}")
        self.date_label.setText(f"<b>Date:</b> {info.get('date', 'Unknown')}")
        
        self._load_cover_art(info.get('thumb'))
        
        self.input_widget.hide()
        self.track_widget.show()
        self.download_button.show()
        self.cancel_button.show()
        self.status_label.clear()
        
        self.setFixedHeight(WINDOW_HEIGHT)

    def _load_cover_art(self, thumb_url):
        if not thumb_url:
            return
            
        try:
            response = requests.get(thumb_url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                pixmap = QPixmap()
                pixmap.loadFromData(response.content)
                scaled_pixmap = pixmap.scaled(
                    100, 100, 
                    Qt.AspectRatioMode.KeepAspectRatio, 
                    Qt.TransformationMode.SmoothTransformation
                )
                self.cover_label.setPixmap(scaled_pixmap)
        except requests.exceptions.RequestException:
            pass

    def handle_fetch_error(self, error):
        self.fetch_button.setEnabled(True)
        self.status_label.setText(f"Error fetching track info: {error}")

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            self.dir_input.setText(directory)

    def open_output_directory(self):
        output_dir = self.dir_input.text().strip() or self.default_music_dir
        os.startfile(output_dir)

    def reset_cookies(self):
        self.cookies_input.setText(DEFAULT_COOKIES)

    def cancel_clicked(self):
        self.track_info = None
        self.status_label.clear()
        self._reset_ui_state()

    def clear_form(self):
        self.url_input.clear()
        self.track_info = None
        self.status_label.clear()
        self.download_button.setText("Download")
        self._reset_ui_state()

    def button_clicked(self):
        if self.download_button.text() == "Clear":
            self.clear_form()
        else:
            self.start_download()

    def start_download(self):
        output_dir = self.dir_input.text().strip()

        if not self.track_info:
            self.status_label.setText("Please fetch track information first")
            return

        if not output_dir:
            output_dir = self.default_music_dir
            self.dir_input.setText(output_dir)

        self.download_button.hide()
        self.cancel_button.hide()
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.status_label.setText("Downloading...")

        if self.worker:
            self.worker.deleteLater()
            
        self.worker = DownloaderWorker(self.track_info, output_dir)
        self.worker.progress.connect(self.update_progress)
        self.worker.progress_status.connect(self.update_progress_status)
        self.worker.finished.connect(self.download_finished)
        self.worker.error.connect(self.download_error)
        self.worker.start()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_progress_status(self, status):
        self.status_label.setText(status)

    def download_finished(self, message):
        self.progress_bar.hide()
        self.status_label.setText(message)
        self.open_button.show()
        self.download_button.setText("Clear") 
        self.download_button.show()
        self.cancel_button.hide()

    def download_error(self, error_message):
        self.progress_bar.hide()
        self.status_label.setText(error_message)
        self.download_button.setText("Retry")
        self.download_button.show()
        self.cancel_button.show()
        
    def closeEvent(self, event):
        if self.fetcher:
            self.fetcher.quit()
            self.fetcher.wait()
        if self.worker:
            self.worker.quit()
            self.worker.wait()
        event.accept()

def main():
    app = QApplication(sys.argv)
    qdarktheme.setup_theme(
        custom_colors={
            "[dark]": {
                "primary": "#2196F3",
            }
        }
    )
    window = SoundCloudGoPlusDownloaderGUI()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()