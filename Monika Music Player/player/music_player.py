# -*- coding: utf-8 -*-
"""Monika Music - standalone companion UI for the MAS submod.
Requires Python 3.9+ and PySide6. No VPet process or code is imported.
"""
import argparse
import ctypes
import json
import os
import random
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

# A GUI-only launch should still explain a missing dependency instead of failing silently.
try:
    import PySide6  # noqa: F401
except Exception:
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                "Monika Music needs PySide6. Run scripts\\install_dependencies.bat inside the submod folder, then try again.",
                "Monika Music - setup required",
                0x10,
            )
        except Exception:
            pass
    raise

from PySide6.QtCore import Qt, QUrl, QTimer, QSize
from PySide6.QtGui import QIcon, QPixmap, QAction, QColor, QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget, QLineEdit,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QSlider,
    QMessageBox, QInputDialog, QMenu, QAbstractItemView, QScrollArea,
    QSizePolicy, QToolButton
)

APP_NAME = "Monika Music"
APP_DIR = Path(__file__).resolve().parent
ASSET_DIR = APP_DIR / "assets"
STATE_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "MonikaMusicPlayer"
STATE_FILE = STATE_DIR / "library.json"
SUPPORTED = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".wma", ".aiff", ".aif"}

# Palette borrows the existing VPet UI's dark-plum + pink outline language,
# with a Spotify-inspired music layout and mint play control.
BG = "#100d14"
SIDEBAR = "#17121d"
PANEL = "#211925"
PANEL_2 = "#2a2030"
BORDER = "#4a3046"
PINK = "#ff69b4"
PINK_LIGHT = "#ffb6c1"
TEXT = "#fff4fa"
MUTED = "#b9a7b8"
GREEN = "#a8f06a"


def duration_text(ms):
    if not ms or ms < 0:
        return "—"
    seconds = int(ms // 1000)
    return "%d:%02d" % (seconds // 60, seconds % 60)


def display_name(path_or_url):
    text = str(path_or_url)
    if text.lower().startswith(("http://", "https://")):
        tail = text.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        return tail or "Online stream"
    return Path(text).stem


def track_from_path(path):
    return {
        "source": str(Path(path).resolve()),
        "title": Path(path).stem,
        "artist": "Local file",
        "album": "Local library",
        "stream": False,
    }


class MasProcessWatcher:
    """Exit the standalone player if the MAS process that opened it exits."""
    def __init__(self, pid, on_exit):
        self.pid = int(pid or 0)
        self.on_exit = on_exit
        self.timer = QTimer()
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.check)
        if self.pid > 0 and os.name == "nt":
            self.timer.start()

    def check(self):
        if not self.pid:
            return
        handle = None
        try:
            kernel32 = ctypes.windll.kernel32
            # SYNCHRONIZE permission is sufficient for WaitForSingleObject.
            handle = kernel32.OpenProcess(0x00100000, False, self.pid)
            if not handle:
                # With SYNCHRONIZE access, a missing handle normally means the
                # MAS process has ended (same-user permissions are expected).
                self.timer.stop()
                self.on_exit()
                return
            result = kernel32.WaitForSingleObject(handle, 0)
            if result == 0:  # WAIT_OBJECT_0: MAS process ended
                self.timer.stop()
                self.on_exit()
        except Exception:
            pass
        finally:
            if handle:
                try:
                    ctypes.windll.kernel32.CloseHandle(handle)
                except Exception:
                    pass


class MusicPlayerWindow(QMainWindow):
    def __init__(self, mas_pid=0):
        super().__init__()
        self.setWindowTitle("Monika Music — Your room, your sound")
        self.setMinimumSize(1040, 660)
        self.resize(1220, 780)
        icon_path = ASSET_DIR / "app_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.library = []
        self.playlists = {"Midnight Drive": [], "Pink Memories": [], "After School": []}
        self.favorites = set()
        self.active_playlist = None
        self.filtered_tracks = []
        self.queue_tracks = []
        self.current_track = None
        self.current_index = -1
        self.shuffle_on = False
        self.repeat_on = False
        self.user_is_seeking = False
        self.page_name = "home"
        self._load_state()

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.72)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_playback_state)
        self.player.errorOccurred.connect(self._on_player_error)
        self.player.mediaStatusChanged.connect(self._on_media_status)

        self._build_ui()
        self._refresh_table()
        self._refresh_sidebar_playlists()
        self._update_now_playing()
        self._show_page("home")

        self.mas_watcher = MasProcessWatcher(mas_pid, self.close)

    def _load_state(self):
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            self.library = [x for x in data.get("library", []) if isinstance(x, dict) and Path(x.get("source", "")).exists()]
            self.playlists.update({k: v for k, v in data.get("playlists", {}).items() if isinstance(v, list)})
            self.favorites = set(data.get("favorites", []))
        except Exception:
            self.library = []

    def _save_state(self):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "library": self.library,
                "playlists": self.playlists,
                "favorites": sorted(self.favorites),
            }
            STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _build_ui(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: %s; color: %s; font-family: 'Segoe UI'; font-size: 13px; }
            QFrame#sidebar { background: %s; border-right: 1px solid %s; }
            QFrame#playerbar { background: #160f19; border-top: 1px solid %s; }
            QLabel#sectionTitle { font-size: 25px; font-weight: 800; color: %s; }
            QLabel#pageTitle { font-size: 30px; font-weight: 800; color: %s; }
            QLabel#muted { color: %s; }
            QPushButton { background: %s; border: 1px solid %s; border-radius: 10px; padding: 8px 13px; color: %s; }
            QPushButton:hover { background: #39253a; border-color: %s; }
            QPushButton:pressed { background: #50304a; }
            QPushButton#navButton { background: transparent; border: none; text-align: left; padding: 10px 12px; color: %s; font-weight: 600; }
            QPushButton#navButton:hover { background: #2b2030; color: %s; }
            QPushButton#navActive { background: #352339; color: %s; border-left: 3px solid %s; text-align: left; border-radius: 8px; padding: 10px 12px; font-weight: 700; }
            QPushButton#primary { background: %s; color: #102008; border: none; border-radius: 21px; font-weight: 800; padding: 10px 18px; }
            QPushButton#primary:hover { background: #c4ff8a; }
            QPushButton#playControl { background: %s; color: #17210c; border: none; border-radius: 23px; font-size: 17px; font-weight: 900; }
            QPushButton#playControl:hover { background: #caff9c; }
            QLineEdit { background: #2a2030; border: 1px solid %s; border-radius: 18px; padding: 10px 15px; color: %s; selection-background-color: %s; }
            QLineEdit:focus { border-color: %s; }
            QTableWidget { background: transparent; border: none; gridline-color: transparent; selection-background-color: #3b2b40; alternate-background-color: #1b1520; }
            QTableWidget::item { padding: 8px 5px; border-bottom: 1px solid #302331; }
            QHeaderView::section { background: transparent; color: %s; border: none; border-bottom: 1px solid %s; padding: 8px 5px; font-weight: 600; }
            QSlider::groove:horizontal { height: 4px; background: #483849; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: %s; border-radius: 2px; }
            QSlider::handle:horizontal { background: %s; width: 11px; margin: -4px 0; border-radius: 5px; }
            QScrollArea { background: transparent; border: none; }
            QToolTip { background: #251a2a; color: %s; border: 1px solid %s; padding: 5px; }
        """ % (BG, TEXT, SIDEBAR, BORDER, BORDER, TEXT, TEXT, MUTED, PANEL_2, BORDER, TEXT, PINK, MUTED, PINK_LIGHT, PINK_LIGHT, PINK, GREEN, GREEN, BORDER, TEXT, GREEN, PINK, MUTED, BORDER, GREEN, GREEN, TEXT, PINK_LIGHT))

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        main_row = QHBoxLayout()
        main_row.setSpacing(0)
        main_row.setContentsMargins(0, 0, 0, 0)
        root_layout.addLayout(main_row, 1)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(225)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(18, 20, 16, 15)
        side.setSpacing(7)

        logo_row = QHBoxLayout()
        logo = QLabel()
        logo.setFixedSize(42, 42)
        logo_img = QPixmap(str(ASSET_DIR / "app_icon.png"))
        if not logo_img.isNull():
            logo.setPixmap(logo_img.scaled(42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo_row.addWidget(logo)
        brand_col = QVBoxLayout()
        brand = QLabel("MONIKA MUSIC")
        brand.setStyleSheet("font-size:14px; font-weight:900; letter-spacing:1px; color:%s;" % PINK_LIGHT)
        brand_sub = QLabel("your own little world")
        brand_sub.setStyleSheet("font-size:10px; color:%s;" % MUTED)
        brand_col.addWidget(brand); brand_col.addWidget(brand_sub)
        logo_row.addLayout(brand_col); logo_row.addStretch()
        side.addLayout(logo_row)
        side.addSpacing(18)

        self.nav_buttons = {}
        for key, label in (("home", "⌂   Home"), ("library", "♫   Your Library"), ("online", "◎   Online audio")):
            btn = QPushButton(label)
            btn.setObjectName("navButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, k=key: self._show_page(k))
            self.nav_buttons[key] = btn
            side.addWidget(btn)
        side.addSpacing(20)
        side.addWidget(self._side_label("YOUR COLLECTION"))
        new_playlist_btn = QPushButton("＋  Create playlist")
        new_playlist_btn.setObjectName("navButton")
        new_playlist_btn.clicked.connect(self._create_playlist)
        side.addWidget(new_playlist_btn)
        self.playlist_nav = QVBoxLayout()
        self.playlist_nav.setSpacing(2)
        side.addLayout(self.playlist_nav)
        side.addStretch(1)

        bottom_side = QLabel("♡  Made with a little Monika magic")
        bottom_side.setStyleSheet("color:%s; font-size:10px;" % MUTED)
        bottom_side.setWordWrap(True)
        side.addWidget(bottom_side)
        main_row.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        self.pages.setMinimumWidth(600)
        main_row.addWidget(self.pages, 1)
        self.pages.addWidget(self._build_home_page())
        self.pages.addWidget(self._build_library_page())
        self.pages.addWidget(self._build_online_page())

        root_layout.addWidget(self._build_player_bar())
        self.setCentralWidget(root)

    def _side_label(self, text):
        label = QLabel(text)
        label.setStyleSheet("color:%s; font-size:10px; font-weight:800; letter-spacing:1px;" % MUTED)
        return label

    def _new_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 23, 28, 18)
        layout.setSpacing(16)
        return page, layout

    def _build_home_page(self):
        page, layout = self._new_page()
        top = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search your library...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._refresh_table)
        top.addWidget(self.search_box, 1)
        add_btn = QPushButton("＋ Add music")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self._add_files)
        top.addWidget(add_btn)
        layout.addLayout(top)

        banner = QFrame()
        banner.setMinimumHeight(195)
        banner.setMaximumHeight(220)
        banner.setStyleSheet("QFrame { border: 1px solid #5a3450; border-radius: 18px; background: #2a1a2c; }")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(24, 18, 24, 18)
        left = QVBoxLayout(); left.setSpacing(8)
        kicker = QLabel("A LITTLE SPACE JUST FOR YOU")
        kicker.setStyleSheet("color:%s; font-size:10px; letter-spacing:2px; font-weight:800;" % PINK_LIGHT)
        title = QLabel("Your room.\nYour sound.")
        title.setStyleSheet("font-size:32px; font-weight:900; color:#fff4fa; line-height:1.0;")
        subtitle = QLabel("Put on something you love and stay a while.")
        subtitle.setStyleSheet("color:#d9bed4; font-size:12px;")
        open_btn = QPushButton("▶  Listen now")
        open_btn.setObjectName("primary")
        open_btn.setFixedWidth(135)
        open_btn.clicked.connect(lambda: self._show_page("library"))
        left.addWidget(kicker); left.addWidget(title); left.addWidget(subtitle); left.addSpacing(4); left.addWidget(open_btn); left.addStretch()
        banner_layout.addLayout(left, 1)
        banner_art = QLabel()
        banner_art.setFixedSize(215, 150)
        pix = QPixmap(str(ASSET_DIR / "banner_art.png"))
        if not pix.isNull():
            banner_art.setPixmap(pix.scaled(banner_art.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        banner_art.setAlignment(Qt.AlignCenter)
        banner_art.setStyleSheet("border:none; background:transparent;")
        banner_layout.addWidget(banner_art)
        layout.addWidget(banner)

        header = QHBoxLayout()
        header.addWidget(self._section_label("Made for your mood")); header.addStretch()
        layout.addLayout(header)
        card_row = QHBoxLayout(); card_row.setSpacing(12)
        cards = [
            ("cover_midnight.png", "Midnight Drive", "Soft sounds for late hours"),
            ("cover_pink.png", "Pink Memories", "A little pink, a little wistful"),
            ("cover_focus.png", "After School", "Background music & calm"),
            ("cover_heart.png", "Liked songs", "Your personal favorites"),
        ]
        for cover, name, desc in cards:
            card_row.addWidget(self._make_mix_card(cover, name, desc), 1)
        layout.addLayout(card_row)

        recent_header = QHBoxLayout()
        recent_header.addWidget(self._section_label("Your library")); recent_header.addStretch()
        see_all = QPushButton("See all")
        see_all.clicked.connect(lambda: self._show_page("library"))
        recent_header.addWidget(see_all)
        layout.addLayout(recent_header)
        self.home_table = self._make_track_table()
        self.home_table.setMaximumHeight(220)
        layout.addWidget(self.home_table, 1)
        return page

    def _section_label(self, text):
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        label.setStyleSheet("font-size:21px; font-weight:800; color:%s;" % TEXT)
        return label

    def _make_mix_card(self, cover, name, desc):
        card = QFrame()
        card.setCursor(Qt.PointingHandCursor)
        card.setMinimumWidth(110)
        card.setStyleSheet("QFrame { background:#211925; border:1px solid #3c2a3b; border-radius:12px; } QFrame:hover { background:#302136; border-color:#704563; }")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 10, 10, 10); lay.setSpacing(7)
        cover_label = QLabel()
        cover_label.setAlignment(Qt.AlignCenter)
        cover_label.setMinimumHeight(95)
        cover_label.setMaximumHeight(125)
        pix = QPixmap(str(ASSET_DIR / cover))
        if not pix.isNull():
            cover_label.setPixmap(pix.scaled(128, 112, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        cover_label.setStyleSheet("border:none; background:transparent;")
        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight:800; font-size:12px; border:none; background:transparent;")
        name_label.setWordWrap(True)
        desc_label = QLabel(desc)
        desc_label.setStyleSheet("color:%s; font-size:10px; border:none; background:transparent;" % MUTED)
        desc_label.setWordWrap(True)
        lay.addWidget(cover_label); lay.addWidget(name_label); lay.addWidget(desc_label)
        card.mousePressEvent = lambda event, n=name: self._open_mix(n)
        return card

    def _build_library_page(self):
        page, layout = self._new_page()
        head = QHBoxLayout()
        title = QLabel("Your Library"); title.setObjectName("pageTitle")
        head.addWidget(title); head.addStretch()
        add_files = QPushButton("＋ Add tracks"); add_files.setObjectName("primary"); add_files.clicked.connect(self._add_files)
        add_folder = QPushButton("＋ Add folder"); add_folder.clicked.connect(self._add_folder)
        head.addWidget(add_files); head.addWidget(add_folder)
        layout.addLayout(head)
        blurb = QLabel("Local files stay on your PC. Right-click a track to like it or add it to a playlist.")
        blurb.setStyleSheet("color:%s;" % MUTED)
        layout.addWidget(blurb)
        self.library_search = QLineEdit()
        self.library_search.setPlaceholderText("Filter tracks by title or file path...")
        self.library_search.setClearButtonEnabled(True)
        self.library_search.textChanged.connect(self._refresh_table)
        layout.addWidget(self.library_search)
        self.library_table = self._make_track_table()
        layout.addWidget(self.library_table, 1)
        return page

    def _build_online_page(self):
        page, layout = self._new_page()
        title = QLabel("Online audio"); title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Play a direct audio stream URL or open an official music search in your browser.")
        subtitle.setStyleSheet("color:%s;" % MUTED)
        layout.addWidget(subtitle)

        card = QFrame()
        card.setStyleSheet("QFrame {background:%s; border:1px solid %s; border-radius:16px;}" % (PANEL, BORDER))
        card_layout = QVBoxLayout(card); card_layout.setContentsMargins(22, 22, 22, 22); card_layout.setSpacing(12)
        heading = QLabel("Play from a direct link")
        heading.setStyleSheet("font-size:19px; font-weight:800; border:none;")
        card_layout.addWidget(heading)
        url_row = QHBoxLayout()
        self.stream_url = QLineEdit()
        self.stream_url.setPlaceholderText("https://example.com/audio-file.mp3")
        url_row.addWidget(self.stream_url, 1)
        play_url = QPushButton("▶  Play URL"); play_url.setObjectName("primary"); play_url.clicked.connect(self._play_stream_url)
        url_row.addWidget(play_url)
        card_layout.addLayout(url_row)
        note = QLabel("Supports direct links to audio files or streams. Pages that require sign-in, subscriptions, DRM, or a special player are not played inside this app.")
        note.setWordWrap(True); note.setStyleSheet("color:%s; border:none; font-size:11px;" % MUTED)
        card_layout.addWidget(note)
        layout.addWidget(card)

        search_card = QFrame()
        search_card.setStyleSheet("QFrame {background:%s; border:1px solid %s; border-radius:16px;}" % (PANEL, BORDER))
        search_layout = QVBoxLayout(search_card); search_layout.setContentsMargins(22, 20, 22, 20); search_layout.setSpacing(10)
        search_title = QLabel("Search online"); search_title.setStyleSheet("font-size:19px; font-weight:800; border:none;")
        search_layout.addWidget(search_title)
        self.web_search = QLineEdit(); self.web_search.setPlaceholderText("Enter a song, artist, or album...")
        search_layout.addWidget(self.web_search)
        web_row = QHBoxLayout()
        youtube_btn = QPushButton("Search YouTube Music"); youtube_btn.clicked.connect(self._search_youtube_music)
        spotify_btn = QPushButton("Open Spotify web"); spotify_btn.clicked.connect(self._open_spotify_web)
        web_row.addWidget(youtube_btn); web_row.addWidget(spotify_btn); web_row.addStretch()
        search_layout.addLayout(web_row)
        layout.addWidget(search_card)
        layout.addStretch(1)
        return page

    def _make_track_table(self):
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["# / ♡", "TITLE", "SOURCE", "TIME"])
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(lambda pos, t=table: self._show_track_menu(t, pos))
        table.cellDoubleClicked.connect(lambda row, col, t=table: self._play_table_row(t, row))
        table.setMinimumHeight(150)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        return table

    def _build_player_bar(self):
        bar = QFrame(); bar.setObjectName("playerbar"); bar.setMinimumHeight(92); bar.setMaximumHeight(100)
        main = QHBoxLayout(bar); main.setContentsMargins(20, 10, 20, 10); main.setSpacing(16)

        self.now_cover = QLabel(); self.now_cover.setFixedSize(56, 56)
        self._set_cover(self.now_cover, "cover_heart.png", 56)
        main.addWidget(self.now_cover)
        track_col = QVBoxLayout(); track_col.setSpacing(4)
        self.now_title = QLabel("Choose a song to begin")
        self.now_title.setStyleSheet("font-weight:800; color:%s;" % TEXT)
        self.now_artist = QLabel("Your music, your space")
        self.now_artist.setStyleSheet("color:%s; font-size:11px;" % MUTED)
        track_col.addWidget(self.now_title); track_col.addWidget(self.now_artist)
        main.addLayout(track_col, 1)
        like = QPushButton("♡"); like.setFixedSize(32, 32); like.setToolTip("Like current song"); like.clicked.connect(self._toggle_current_favorite)
        main.addWidget(like); self.like_button = like

        middle = QVBoxLayout(); middle.setSpacing(3)
        controls = QHBoxLayout(); controls.setSpacing(10); controls.setAlignment(Qt.AlignCenter)
        self.shuffle_btn = self._small_control("⤨", "Toggle shuffle", lambda: self._toggle_mode("shuffle"))
        self.prev_btn = self._small_control("|◀", "Previous track", self._previous_track)
        self.play_btn = QPushButton("▶"); self.play_btn.setObjectName("playControl"); self.play_btn.setFixedSize(44, 44); self.play_btn.clicked.connect(self._toggle_playback)
        self.next_btn = self._small_control("▶|", "Next track", self._next_track)
        self.repeat_btn = self._small_control("↻", "Toggle repeat", lambda: self._toggle_mode("repeat"))
        for w in (self.shuffle_btn, self.prev_btn, self.play_btn, self.next_btn, self.repeat_btn): controls.addWidget(w)
        middle.addLayout(controls)
        seek = QHBoxLayout(); seek.setSpacing(7)
        self.elapsed_label = QLabel("0:00"); self.elapsed_label.setStyleSheet("font-size:10px; color:%s;" % MUTED)
        self.seek_slider = QSlider(Qt.Horizontal); self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderPressed.connect(lambda: setattr(self, "user_is_seeking", True))
        self.seek_slider.sliderReleased.connect(self._seek_released)
        self.duration_label = QLabel("0:00"); self.duration_label.setStyleSheet("font-size:10px; color:%s;" % MUTED)
        seek.addWidget(self.elapsed_label); seek.addWidget(self.seek_slider, 1); seek.addWidget(self.duration_label)
        middle.addLayout(seek)
        main.addLayout(middle, 2)

        volume_row = QHBoxLayout(); volume_row.setSpacing(6)
        vol_icon = QLabel("◖))"); vol_icon.setStyleSheet("color:%s;" % MUTED)
        self.volume_slider = QSlider(Qt.Horizontal); self.volume_slider.setFixedWidth(100); self.volume_slider.setRange(0, 100); self.volume_slider.setValue(72); self.volume_slider.valueChanged.connect(lambda v: self.audio_output.setVolume(v / 100.0))
        volume_row.addWidget(vol_icon); volume_row.addWidget(self.volume_slider)
        main.addLayout(volume_row)
        return bar

    def _small_control(self, text, tip, callback):
        b = QPushButton(text); b.setFixedSize(32, 32); b.setToolTip(tip)
        b.setStyleSheet("QPushButton {background:transparent; border:none; color:%s; font-size:16px; padding:3px;} QPushButton:hover {color:%s; background:#302136;}" % (MUTED, PINK_LIGHT))
        b.clicked.connect(callback)
        return b

    def _set_cover(self, label, filename, size):
        pix = QPixmap(str(ASSET_DIR / filename))
        if not pix.isNull():
            label.setPixmap(pix.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        label.setAlignment(Qt.AlignCenter)

    def _show_page(self, name):
        self.page_name = name
        index = {"home": 0, "library": 1, "online": 2}.get(name, 0)
        self.pages.setCurrentIndex(index)
        for key, btn in self.nav_buttons.items():
            btn.setObjectName("navActive" if key == name else "navButton")
            btn.style().unpolish(btn); btn.style().polish(btn)
        self.active_playlist = None if name != "library" else self.active_playlist
        self._refresh_table()

    def _refresh_sidebar_playlists(self):
        while self.playlist_nav.count():
            item = self.playlist_nav.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for name in self.playlists:
            btn = QPushButton("♫  " + name)
            btn.setObjectName("navButton")
            btn.setToolTip("Open playlist: " + name)
            btn.clicked.connect(lambda checked=False, n=name: self._open_mix(n))
            self.playlist_nav.addWidget(btn)

    def _open_mix(self, name):
        if name == "Liked songs":
            self.active_playlist = "Liked songs"
        elif name in self.playlists:
            self.active_playlist = name
        else:
            self.active_playlist = None
        self._show_page("library")
        if hasattr(self, "library_search"):
            self.library_search.setText("")
        self._refresh_table()

    def _visible_library(self):
        tracks = list(self.library)
        if self.active_playlist == "Liked songs":
            tracks = [t for t in tracks if t["source"] in self.favorites]
        elif self.active_playlist in self.playlists:
            allowed = set(self.playlists[self.active_playlist])
            tracks = [t for t in tracks if t["source"] in allowed]
        search = ""
        if hasattr(self, "library_search") and self.page_name == "library":
            search = self.library_search.text().strip().lower()
        elif hasattr(self, "search_box") and self.page_name == "home":
            search = self.search_box.text().strip().lower()
        if search:
            tracks = [t for t in tracks if search in t.get("title", "").lower() or search in t.get("source", "").lower() or search in t.get("artist", "").lower()]
        return tracks

    def _refresh_table(self, *args):
        tracks = self._visible_library() if hasattr(self, "library") else []
        if hasattr(self, "library_table"):
            self._fill_table(self.library_table, tracks)
        if hasattr(self, "home_table"):
            self._fill_table(self.home_table, tracks[-6:][::-1])
        self.filtered_tracks = tracks

    def _fill_table(self, table, tracks):
        table.setRowCount(0)
        for i, track in enumerate(tracks):
            row = table.rowCount(); table.insertRow(row); table.setRowHeight(row, 43)
            source = track.get("source", "")
            heart = "♥" if source in self.favorites else str(i + 1)
            first = QTableWidgetItem(heart)
            first.setTextAlignment(Qt.AlignCenter)
            first.setForeground(QColor(PINK if heart == "♥" else MUTED))
            first.setData(Qt.UserRole, source)
            table.setItem(row, 0, first)
            title = QTableWidgetItem(track.get("title", display_name(source)))
            title.setForeground(QColor(TEXT)); title.setData(Qt.UserRole, source)
            table.setItem(row, 1, title)
            source_text = "Online stream" if track.get("stream") else track.get("artist", "Local file")
            source_item = QTableWidgetItem(source_text)
            source_item.setForeground(QColor(MUTED)); source_item.setData(Qt.UserRole, source)
            table.setItem(row, 2, source_item)
            time_item = QTableWidgetItem("—")
            time_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            time_item.setForeground(QColor(MUTED)); time_item.setData(Qt.UserRole, source)
            table.setItem(row, 3, time_item)
        if not tracks:
            # Keep a clear empty-state row rather than a blank, confusing screen.
            table.setRowCount(1); table.setRowHeight(0, 55)
            empty = QTableWidgetItem("No songs yet — use ‘Add tracks’ to import local music.")
            empty.setForeground(QColor(MUTED)); table.setItem(0, 1, empty)
            for col in (0, 2, 3): table.setItem(0, col, QTableWidgetItem(""))

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add music", str(Path.home()), "Audio files (*.mp3 *.wav *.ogg *.flac *.m4a *.aac *.opus *.wma *.aiff *.aif);;All files (*.*)")
        self._add_paths(paths)

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose a music folder", str(Path.home()))
        if not folder:
            return
        found = []
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if Path(name).suffix.lower() in SUPPORTED:
                    found.append(os.path.join(root, name))
        self._add_paths(found)

    def _add_paths(self, paths):
        known = {t.get("source") for t in self.library}
        count = 0
        for path in paths:
            try:
                if Path(path).suffix.lower() in SUPPORTED and Path(path).is_file() and str(Path(path).resolve()) not in known:
                    track = track_from_path(path)
                    self.library.append(track); known.add(track["source"]); count += 1
            except Exception:
                continue
        self._save_state(); self._refresh_table()
        if count:
            self.statusBar().showMessage("Added %d track(s) to your library." % count, 4500)

    def _create_playlist(self):
        name, ok = QInputDialog.getText(self, "Create playlist", "Playlist name:")
        name = name.strip()
        if ok and name:
            if name in self.playlists:
                QMessageBox.information(self, "Playlist exists", "There's already a playlist with that name.")
                return
            self.playlists[name] = []
            self._save_state(); self._refresh_sidebar_playlists()
            self.statusBar().showMessage("Created playlist: " + name, 3500)

    def _show_track_menu(self, table, pos):
        row = table.rowAt(pos.y())
        if row < 0: return
        item = table.item(row, 1)
        if not item: return
        source = item.data(Qt.UserRole)
        track = next((t for t in self.library if t.get("source") == source), None)
        if not track: return
        menu = QMenu(self)
        play_action = menu.addAction("▶  Play now")
        fav_action = menu.addAction("♥  Remove from liked songs" if source in self.favorites else "♡  Add to liked songs")
        submenu = menu.addMenu("＋  Add to playlist")
        playlist_actions = [(submenu.addAction(name), name) for name in self.playlists]
        chosen = menu.exec(table.viewport().mapToGlobal(pos))
        if chosen == play_action:
            self._play_track(track, self.filtered_tracks)
        elif chosen == fav_action:
            if source in self.favorites: self.favorites.remove(source)
            else: self.favorites.add(source)
            self._save_state(); self._refresh_table(); self._update_now_playing()
        else:
            for action, name in playlist_actions:
                if chosen == action:
                    if source not in self.playlists[name]: self.playlists[name].append(source)
                    self._save_state(); self.statusBar().showMessage("Added to %s" % name, 3500)
                    break

    def _play_table_row(self, table, row):
        item = table.item(row, 1)
        if not item: return
        source = item.data(Qt.UserRole)
        if not source: return
        track = next((t for t in self.library if t.get("source") == source), None)
        if track:
            self._play_track(track, self._visible_library())

    def _play_track(self, track, queue_tracks=None):
        if not track: return
        self.current_track = dict(track)
        self.queue_tracks = list(queue_tracks or self.library)
        if not any(t.get("source") == track.get("source") for t in self.queue_tracks):
            self.queue_tracks.insert(0, track)
        self.current_index = next((i for i, t in enumerate(self.queue_tracks) if t.get("source") == track.get("source")), 0)
        source = track.get("source", "")
        if track.get("stream") or source.lower().startswith(("http://", "https://")):
            self.player.setSource(QUrl(source))
        else:
            self.player.setSource(QUrl.fromLocalFile(source))
        self.player.play()
        self._update_now_playing()
        self.statusBar().showMessage("Playing: " + track.get("title", display_name(source)), 2500)

    def _play_stream_url(self):
        url = self.stream_url.text().strip()
        if not url.lower().startswith(("https://", "http://")):
            QMessageBox.warning(self, "Invalid link", "Please paste an http:// or https:// direct audio URL.")
            return
        track = {"source": url, "title": display_name(url), "artist": "Online stream", "album": "Online", "stream": True}
        self._play_track(track, [track])

    def _toggle_playback(self):
        state = self.player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        elif self.current_track:
            self.player.play()
        elif self.library:
            self._play_track(self.library[0], self.library)
        else:
            self._show_page("library")
            self.statusBar().showMessage("Add a few audio files to get started.", 4000)

    def _next_track(self):
        if not self.queue_tracks: return
        if self.shuffle_on:
            candidates = [i for i in range(len(self.queue_tracks)) if i != self.current_index]
            self.current_index = random.choice(candidates) if candidates else self.current_index
        else:
            self.current_index += 1
            if self.current_index >= len(self.queue_tracks):
                if self.repeat_on: self.current_index = 0
                else: self.current_index = len(self.queue_tracks) - 1; self.player.pause(); return
        self._play_track(self.queue_tracks[self.current_index], self.queue_tracks)

    def _previous_track(self):
        if not self.queue_tracks: return
        if self.player.position() > 3500:
            self.player.setPosition(0); return
        self.current_index = max(0, self.current_index - 1)
        self._play_track(self.queue_tracks[self.current_index], self.queue_tracks)

    def _toggle_mode(self, mode):
        if mode == "shuffle":
            self.shuffle_on = not self.shuffle_on
            self.shuffle_btn.setStyleSheet("color:%s;" % (GREEN if self.shuffle_on else MUTED))
            self.statusBar().showMessage("Shuffle on" if self.shuffle_on else "Shuffle off", 2500)
        else:
            self.repeat_on = not self.repeat_on
            self.repeat_btn.setStyleSheet("color:%s;" % (GREEN if self.repeat_on else MUTED))
            self.statusBar().showMessage("Repeat on" if self.repeat_on else "Repeat off", 2500)

    def _toggle_current_favorite(self):
        if not self.current_track: return
        src = self.current_track.get("source", "")
        if src in self.favorites: self.favorites.remove(src)
        else: self.favorites.add(src)
        self._save_state(); self._refresh_table(); self._update_now_playing()

    def _update_now_playing(self):
        if not self.current_track:
            return
        self.now_title.setText(self.current_track.get("title", "Unknown track"))
        self.now_artist.setText(self.current_track.get("artist", "Local file"))
        self.like_button.setText("♥" if self.current_track.get("source") in self.favorites else "♡")
        self.like_button.setStyleSheet("color:%s; border:none; font-size:18px;" % PINK)
        self._set_cover(self.now_cover, "cover_midnight.png" if self.current_track.get("stream") else "cover_heart.png", 56)

    def _on_position(self, position):
        if not self.user_is_seeking:
            self.seek_slider.setValue(position)
        self.elapsed_label.setText(duration_text(position))

    def _on_duration(self, duration):
        self.seek_slider.setRange(0, max(0, duration))
        self.duration_label.setText(duration_text(duration))
        # Duration appears beside the current row in the library, too.
        self._refresh_table()

    def _seek_released(self):
        self.user_is_seeking = False
        self.player.setPosition(self.seek_slider.value())

    def _on_playback_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setText("Ⅱ" if playing else "▶")

    def _on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.repeat_on:
                self.player.setPosition(0); self.player.play()
            else:
                self._next_track()

    def _on_player_error(self, error, error_string):
        if error != QMediaPlayer.Error.NoError:
            self.statusBar().showMessage("Playback issue: %s" % (error_string or "This format or stream may not be supported."), 7000)

    def _search_youtube_music(self):
        query = self.web_search.text().strip()
        if not query:
            query, ok = QInputDialog.getText(self, "Search YouTube Music", "Song, artist, or album:")
            if not ok or not query.strip(): return
        QDesktopServices.openUrl(QUrl("https://music.youtube.com/search?q=" + quote_plus(query.strip())))

    def _open_spotify_web(self):
        query = self.web_search.text().strip()
        url = "https://open.spotify.com/search/" + quote_plus(query) if query else "https://open.spotify.com/"
        QDesktopServices.openUrl(QUrl(url))

    def closeEvent(self, event):
        try:
            self._save_state()
            if self.mas_watcher:
                self.mas_watcher.timer.stop()
            self.player.stop()
        except Exception:
            pass
        event.accept()


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mas-pid", type=int, default=0)
    args, _ = parser.parse_known_args()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    if (ASSET_DIR / "app_icon.png").exists():
        app.setWindowIcon(QIcon(str(ASSET_DIR / "app_icon.png")))
    window = MusicPlayerWindow(args.mas_pid)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
