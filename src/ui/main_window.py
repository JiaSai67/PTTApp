import sys
import datetime
import os
import subprocess

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QScrollArea, QCheckBox, 
                             QMessageBox, QApplication, QFileIconProvider,
                             QRadioButton, QButtonGroup, QComboBox,
                             QDialog, QFormLayout, QLineEdit, QListWidget,
                             QListWidgetItem, QTextEdit, QSpinBox, QGroupBox)
from PySide6.QtCore import Qt, QThread, Signal, QFileInfo, QTimer
from PySide6.QtGui import QIcon, QFont, QColor
from pynput import keyboard, mouse

from src.core.audio_manager import AudioManager
from src.core.ptt_worker import PTTWorker
from src.ui.overlay import MicOffOverlay
from src.core.config_manager import ConfigManager
from src.ui.theme_utils import get_main_stylesheet, get_theme_colors, get_font

def get_key_name(key):
    if hasattr(key, 'name'):
        return key.name
    elif hasattr(key, 'char'):
        return key.char
    return str(key).strip("'")

class PackageInstallWorker(QThread):
    finished_signal = Signal(bool, str)

    def __init__(self, package_name):
        super().__init__()
        self.package_name = package_name

    def run(self):
        try:
            cmd = [sys.executable, "-m", "pip", "install", self.package_name]
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            res = subprocess.run(cmd, creationflags=flags, capture_output=True, text=True, encoding='utf-8', errors='replace')
            if res.returncode == 0:
                self.finished_signal.emit(True, "安裝成功！")
            else:
                self.finished_signal.emit(False, res.stderr or res.stdout or "未知錯誤")
        except Exception as e:
            self.finished_signal.emit(False, str(e))

class HotkeyRecorder(QThread):
    hotkey_detected = Signal(str)

    def __init__(self):
        super().__init__()
        self.k_listener = None
        self.m_listener = None
        self.pressed_keys = set()
        self.running = True

    def run(self):
        self.k_listener = keyboard.Listener(on_press=self._on_k_press, on_release=self._on_k_release)
        self.m_listener = mouse.Listener(on_click=self._on_m_click)
        self.k_listener.start()
        self.m_listener.start()
        self.k_listener.join()
        self.m_listener.join()

    def _on_k_press(self, key):
        name = get_key_name(key)
        if name:
            self.pressed_keys.add(name)

    def _on_k_release(self, key):
        if self.pressed_keys:
            self._finish()
            return False

    def _on_m_click(self, x, y, button, pressed):
        name = get_key_name(button)
        if name in ['left', 'right']: return 
        
        if name:
            if pressed:
                self.pressed_keys.add(name)
            elif self.pressed_keys:
                self._finish()
                return False

    def _finish(self):
        if not self.running: return
        self.running = False
        hotkey_str = '+'.join(sorted(self.pressed_keys))
        self.hotkey_detected.emit(hotkey_str)
        if self.k_listener: self.k_listener.stop()
        if self.m_listener: self.m_listener.stop()

    def cancel(self):
        self.running = False
        if self.k_listener: self.k_listener.stop()
        if self.m_listener: self.m_listener.stop()

class IconMoverThread(QThread):
    position_changed = Signal(int, int)
    adjustment_finished = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.m_listener = None
        self.running = True

    def run(self):
        self.m_listener = mouse.Listener(on_move=self._on_m_move, on_click=self._on_m_click)
        self.m_listener.start()
        self.m_listener.join()

    def _on_m_move(self, x, y):
        if self.running:
            self.position_changed.emit(int(x), int(y))

    def _on_m_click(self, x, y, button, pressed):
        name = get_key_name(button)
        if name == 'left' and pressed:
            if self.running:
                self.running = False
                self.adjustment_finished.emit(int(x), int(y))
                return False

    def cancel(self):
        self.running = False
        if self.m_listener: self.m_listener.stop()


class LoopBeSignalDialog(QDialog):
    """Studio One 控制項目新增/編輯視窗"""
    def __init__(self, parent=None, signal_data=None):
        super().__init__(parent)
        self.setWindowTitle("新增/編輯 Studio One 控制項目")
        self.setFixedSize(380, 200)
        self.signal_data = signal_data or {}
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("自訂設定 (Custom)")
        self.preset_combo.addItem("👥 電腦觀眾 (CueMix 開關)", {'name': '電腦觀眾 (CueMix 開關)', 'cc': 15})
        self.preset_combo.addItem("🎙️ 軌道 1 (麥克風整軌)", {'name': '軌道 1 (麥克風整軌)', 'cc': 14})
        self.preset_combo.addItem("📱 手機 OTG 開關", {'name': '手機 OTG 開關', 'cc': 16})
        self.preset_combo.addItem("🎙️ 軌道 2 (講話)", {'name': '軌道 2 (講話)', 'cc': 17})
        self.preset_combo.addItem("🔊 總輸出 (Master 音量軌)", {'name': '總輸出 (Master 音量軌)', 'cc': 18})
        
        self.name_input = QLineEdit(self.signal_data.get('name', '電腦觀眾 (CueMix 開關)'))
        self.cc_spin = QSpinBox()
        self.cc_spin.setRange(0, 127)
        self.cc_spin.setValue(self.signal_data.get('cc_num', 15))
        
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        
        form_layout.addRow("快速範本:", self.preset_combo)
        form_layout.addRow("控制名稱:", self.name_input)
        form_layout.addRow("MIDI CC 代碼:", self.cc_spin)
        layout.addLayout(form_layout)
        
        tip_lbl = QLabel("💡 一條 LoopBe 傳輸線可同時獨立控制 128 個不同的 CC 代碼！")
        tip_lbl.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(tip_lbl)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("確認儲存")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
    def _on_preset_changed(self, idx):
        data = self.preset_combo.currentData()
        if data:
            self.name_input.setText(data['name'])
            self.cc_spin.setValue(data['cc'])

    def get_data(self):
        import uuid
        name = self.name_input.text().strip() or "未命名控制項目"
        cc = self.cc_spin.value()
        return {
            'id': self.signal_data.get('id', str(uuid.uuid4())),
            'name': name,
            'cc_num': cc,
            'channel': 0,
            'enabled': self.signal_data.get('enabled', True)
        }


class LoopBeSignalWidget(QWidget):
    def __init__(self, signal_data):
        super().__init__()
        self.signal_data = signal_data
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        
        colors = get_theme_colors()
        self.setStyleSheet(f"background-color: {colors.bg_card}; color: {colors.text_main}; border-radius: 8px;")
        
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(signal_data.get('enabled', True))
        
        lbl_text = f"🎚️ {signal_data.get('name', '控制項目')}  (CC: {signal_data.get('cc_num', 14)})"
        self.name_lbl = QLabel(lbl_text)
        self.name_lbl.setFont(get_font(10, bold=True))
        
        self.test_btn = QPushButton("⚡ 測試")
        self.test_btn.setFixedSize(55, 28)
        self.test_btn.setFont(get_font(9))
        self.test_btn.setStyleSheet(f"background-color: {colors.primary}; color: white; border: none; border-radius: 4px;")
        
        self.edit_btn = QPushButton("✏️ 編輯")
        self.edit_btn.setFixedSize(60, 28)
        self.edit_btn.setFont(get_font(9))
        self.edit_btn.setStyleSheet(f"background-color: #444; color: white; border: none; border-radius: 4px;")
        
        self.delete_btn = QPushButton("🗑️ 刪除")
        self.delete_btn.setFixedSize(55, 28)
        self.delete_btn.setFont(get_font(9))
        self.delete_btn.setStyleSheet(f"background-color: {colors.error_bg}; color: white; border: none; border-radius: 4px;")
        
        layout.addWidget(self.checkbox)
        layout.addSpacing(8)
        layout.addWidget(self.name_lbl, stretch=1)
        layout.addWidget(self.test_btn)
        layout.addSpacing(4)
        layout.addWidget(self.edit_btn)
        layout.addSpacing(4)
        layout.addWidget(self.delete_btn)


class StudioOneGuideDialog(QDialog):
    """Studio One 30 秒快速綁定指引"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📖 Studio One 30 秒快速綁定指南")
        self.resize(480, 420)
        
        layout = QVBoxLayout(self)
        colors = get_theme_colors()
        
        title_lbl = QLabel("Studio One 設定步驟（只需做一次）：")
        title_lbl.setFont(get_font(11, bold=True))
        layout.addWidget(title_lbl)
        
        guide_text = QTextEdit()
        guide_text.setReadOnly(True)
        guide_text.setStyleSheet(f"background-color: {colors.bg_card}; color: {colors.text_main}; border: 1px solid {colors.border}; border-radius: 6px; padding: 8px; font-size: 13px; line-height: 1.5;")
        
        content = """<b>【步驟 1：在 Studio One 新增控制界面】</b><br>
1. 打開 Studio One ➔ 點擊上方選單 <b>「選項 (Options)」➔「外部裝置 (External Devices)」</b>。<br>
2. 點擊 <b>「新增 (Add)」</b>。<br>
3. 在左側清單最上方選擇：<b>「🎚️ 新建控制界面 (New Control Surface)」</b>。<br>
4. 「接收自 (Receive From)」下拉選單選擇：<b>LoopBe Internal MIDI</b>（或 loopMIDI Port）。<br>
5. 「發送到 (Send To)」選擇：<b>無 (None)</b> ➔ 點擊 <b>確定</b> 儲存。<br><br>

<b>【步驟 2：綁定「電腦觀眾 (CueMix)」開關】</b><br>
1. 在 Studio One 找到您的麥克風軌道，用滑鼠點一下 <b>⏻ 電腦觀眾</b> 開關。<br>
2. 回到 PTTApp，在「電腦觀眾」那一行點擊 <b>「⚡ 測試」</b> 按鈕。<br>
3. 回到 Studio One，看左上角的 <b>🖐 静音 / CueMix02</b>，點擊連動鎖鏈圖標，即可完成綁定！<br><br>

<b>【步驟 3：綁定「軌道整軌靜音 (M)」】</b><br>
1. 在 Studio One 麥克風軌道的 <b>M (靜音)</b> 按鈕上 <b>點右鍵</b> ➔ 選擇 <b>「分配控制...」</b>。<br>
2. 回到 PTTApp 點擊「軌道 1 麥克風」那一行的 <b>「⚡ 測試」</b> 按鈕，立即完成綁定！"""
        
        guide_text.setHtml(content)
        layout.addWidget(guide_text)
        
        close_btn = QPushButton("我知道了")
        close_btn.clicked.connect(self.accept)
        close_btn.setFixedHeight(34)
        layout.addWidget(close_btn)


class DiagnosticDialog(QDialog):
    """深度系統與環境診斷對話框"""
    def __init__(self, parent=None, log_path=None):
        super().__init__(parent)
        self.setWindowTitle("🛠️ PTTApp 深度系統環境診斷報告")
        self.resize(620, 500)
        self.log_path = log_path
        
        layout = QVBoxLayout(self)
        colors = get_theme_colors()
        
        title_lbl = QLabel("系統與虛擬傳輸線診斷結果：")
        title_lbl.setFont(get_font(11, bold=True))
        layout.addWidget(title_lbl)
        
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Consolas", 9))
        self.text_edit.setStyleSheet(f"background-color: {colors.bg_card}; color: {colors.text_main}; border: 1px solid {colors.border}; border-radius: 6px; padding: 8px;")
        
        if log_path and os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    self.text_edit.setPlainText(f.read())
            except Exception:
                pass
                
        layout.addWidget(self.text_edit)
        
        btn_box = QHBoxLayout()
        copy_btn = QPushButton("📋 一鍵複製診斷內容")
        copy_btn.setFixedHeight(34)
        copy_btn.clicked.connect(self._copy_content)
        
        open_btn = QPushButton("📁 以記事本開啟檔案")
        open_btn.setFixedHeight(34)
        open_btn.clicked.connect(self._open_file)
        
        close_btn = QPushButton("關閉")
        close_btn.setFixedHeight(34)
        close_btn.clicked.connect(self.accept)
        
        btn_box.addWidget(copy_btn)
        btn_box.addWidget(open_btn)
        btn_box.addWidget(close_btn)
        layout.addLayout(btn_box)

    def _copy_content(self):
        cb = QApplication.clipboard()
        cb.setText(self.text_edit.toPlainText())
        QMessageBox.information(self, "成功", "✅ 診斷內容已複製到剪貼簿！您可以直接貼上傳給開發者。")

    def _open_file(self):
        if self.log_path and os.path.exists(self.log_path):
            try:
                subprocess.Popen(['notepad.exe', self.log_path])
            except Exception:
                os.startfile(self.log_path)


class AppItemWidget(QWidget):
    def __init__(self, app_info):
        super().__init__()
        self.app_info = app_info
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        colors = get_theme_colors()
        self.setStyleSheet(f"background-color: {colors.bg_card}; color: {colors.text_main}; border-radius: 5px;")

        self.checkbox = QCheckBox()
        layout.addWidget(self.checkbox)
        
        self.icon_label = QLabel("🎤")
        self.icon_label.setFont(QFont("Segoe UI Emoji", 14))
        layout.addWidget(self.icon_label)
        
        self.name_label = QLabel(app_info['name'])
        self.name_label.setFont(get_font(10))
        layout.addWidget(self.name_label)
        
        layout.addStretch()

        self.delete_btn = QPushButton("🗑️")
        self.delete_btn.setFixedSize(30, 30)
        self.delete_btn.setStyleSheet("background: transparent; border: none;")
        self.delete_btn.hide()
        layout.addWidget(self.delete_btn)


VERSION = "1.3.1"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"按鍵發話 (PTT) 控制器 v{VERSION}")
        self.resize(480, 580)

        self.config = ConfigManager()
        self.audio_manager = AudioManager(self.config)
        self.overlay = MicOffOverlay(self.config)
        self.ptt_worker = PTTWorker(self.audio_manager)
        self.ptt_worker.state_changed.connect(self.on_ptt_state_changed)
        
        self.hotkey = self.config.get('hotkey')
        self.app_widgets = []
        self.listener_thread = None
        self.mover_thread = None
        
        self.init_ui()
        self.refresh_apps()

    def init_ui(self):
        self.setStyleSheet(get_main_stylesheet())
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Header
        header_layout = QHBoxLayout()
        header_lbl = QLabel("🎤 靜音控制目標:")
        header_lbl.setFont(get_font(11, bold=True))
        
        self.engine_combo = QComboBox()
        self.engine_combo.setFont(get_font(10))
        self.engine_combo.addItems([
            "Windows 系統麥克風 (預設模式)",
            "Voicemeeter 路由控制",
            "Studio One (LoopBe 虛擬傳輸線模式)"
        ])
        
        saved_engine = self.config.get('engine_type') or 'windows'
        if saved_engine == 'voicemeeter':
            self.engine_combo.setCurrentIndex(1)
        elif saved_engine in ['studioone', 'studioone_loopbe', 'studioone_osc']:
            self.engine_combo.setCurrentIndex(2)
        else:
            self.engine_combo.setCurrentIndex(0)
            
        self.audio_manager.set_engine(saved_engine)
        self.engine_combo.currentIndexChanged.connect(self.on_engine_changed)
        
        header_layout.addWidget(header_lbl)
        header_layout.addWidget(self.engine_combo)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        # Matrix Controls (Voicemeeter)
        self.matrix_frame = QWidget()
        matrix_layout = QHBoxLayout(self.matrix_frame)
        matrix_layout.setContentsMargins(0, 0, 0, 0)
        
        self.matrix_in_combo = QComboBox()
        self.matrix_out_combo = QComboBox()
        self.matrix_add_btn = QPushButton("➕ 新增路由控制")
        self.matrix_add_btn.clicked.connect(self.add_matrix_route)
        
        matrix_layout.addWidget(QLabel("輸入:"))
        matrix_layout.addWidget(self.matrix_in_combo, stretch=1)
        matrix_layout.addWidget(QLabel("➜ 輸出:"))
        matrix_layout.addWidget(self.matrix_out_combo, stretch=1)
        matrix_layout.addWidget(self.matrix_add_btn)
        self.matrix_frame.hide()
        main_layout.addWidget(self.matrix_frame)
        
        # Studio One LoopBe Controls
        self.s1_frame = QWidget()
        s1_layout = QVBoxLayout(self.s1_frame)
        s1_layout.setContentsMargins(0, 0, 0, 4)
        s1_layout.setSpacing(6)
        
        self.s1_status_lbl = QLabel()
        self.s1_status_lbl.setFont(get_font(10, bold=True))
        self.s1_status_lbl.setAlignment(Qt.AlignCenter)
        
        # Missing driver action box
        self.s1_missing_box = QWidget()
        missing_layout = QVBoxLayout(self.s1_missing_box)
        missing_layout.setContentsMargins(0, 0, 0, 0)
        missing_layout.setSpacing(4)
        
        self.s1_install_btn = QPushButton("📥 一鍵安裝 LoopBe1 虛擬傳輸線 (微軟官方認證)")
        self.s1_install_btn.setFixedHeight(34)
        self.s1_install_btn.setFont(get_font(10, bold=True))
        self.s1_install_btn.setStyleSheet("background-color: #0078D4; color: white; border: none; border-radius: 5px;")
        self.s1_install_btn.clicked.connect(self.install_loopbe)
        
        missing_sub_box = QHBoxLayout()
        self.s1_rescan_btn = QPushButton("🔄 重新整理 / 掃描")
        self.s1_rescan_btn.setFixedHeight(30)
        self.s1_rescan_btn.clicked.connect(self.refresh_apps)
        
        self.s1_diag_btn1 = QPushButton("🛠️ 檢查環境 / 診斷報告")
        self.s1_diag_btn1.setFixedHeight(30)
        self.s1_diag_btn1.clicked.connect(self.run_diagnostic)
        
        missing_sub_box.addWidget(self.s1_rescan_btn)
        missing_sub_box.addWidget(self.s1_diag_btn1)
        
        missing_layout.addWidget(self.s1_install_btn)
        missing_layout.addLayout(missing_sub_box)
        
        # Ready action box
        self.s1_btn_widget = QWidget()
        s1_btn_layout = QHBoxLayout(self.s1_btn_widget)
        s1_btn_layout.setContentsMargins(0, 0, 0, 0)
        s1_btn_layout.setSpacing(6)
        
        self.s1_add_btn = QPushButton("➕ 新增控制項目")
        self.s1_add_btn.setFixedHeight(32)
        self.s1_add_btn.setFont(get_font(10))
        self.s1_add_btn.clicked.connect(self.add_loopbe_signal)
        
        self.s1_guide_btn = QPushButton("📖 30 秒設定教學")
        self.s1_guide_btn.setFixedHeight(32)
        self.s1_guide_btn.setFont(get_font(10))
        self.s1_guide_btn.clicked.connect(self.open_studioone_guide)
        
        self.s1_diag_btn2 = QPushButton("🛠️ 診斷報告")
        self.s1_diag_btn2.setFixedHeight(32)
        self.s1_diag_btn2.setFont(get_font(10))
        self.s1_diag_btn2.clicked.connect(self.run_diagnostic)
        
        s1_btn_layout.addWidget(self.s1_add_btn)
        s1_btn_layout.addWidget(self.s1_guide_btn)
        s1_btn_layout.addWidget(self.s1_diag_btn2)
        
        s1_layout.addWidget(self.s1_status_lbl)
        s1_layout.addWidget(self.s1_missing_box)
        s1_layout.addWidget(self.s1_btn_widget)
        
        self.s1_frame.hide()
        main_layout.addWidget(self.s1_frame)

        # Apps List
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("scroll_content")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignTop)
        self.scroll_area.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll_area)

        # Refresh btn
        self.refresh_btn = QPushButton("🔄 重新整理裝置清單")
        self.refresh_btn.clicked.connect(self.refresh_apps)
        main_layout.addWidget(self.refresh_btn)

        # Mode Selection
        mode_layout = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_ptt_radio = QRadioButton("模式 1：按住發話 (放開靜音)")
        self.mode_ptt_radio.setFont(get_font(10))
        self.mode_toggle_radio = QRadioButton("模式 2：切換模式 (按一下開/關)")
        self.mode_toggle_radio.setFont(get_font(10))
        
        if self.config.get('mode') == 'toggle':
            self.mode_toggle_radio.setChecked(True)
        else:
            self.mode_ptt_radio.setChecked(True)
            
        self.mode_ptt_radio.toggled.connect(self.save_mode)
        self.mode_toggle_radio.toggled.connect(self.save_mode)
        
        self.mode_group.addButton(self.mode_ptt_radio)
        self.mode_group.addButton(self.mode_toggle_radio)
        mode_layout.addWidget(self.mode_ptt_radio)
        mode_layout.addWidget(self.mode_toggle_radio)
        main_layout.addLayout(mode_layout)

        # Hotkey setup
        hotkey_layout = QHBoxLayout()
        if self.hotkey:
            self.hotkey_lbl = QLabel(f"目前快捷鍵: {self.hotkey}")
        else:
            self.hotkey_lbl = QLabel("目前快捷鍵: 無")
        self.hotkey_lbl.setFont(get_font(10))
        
        self.set_hotkey_btn = QPushButton("設定快捷鍵")
        self.set_hotkey_btn.clicked.connect(self.start_hotkey_listen)
        
        self.cancel_hotkey_btn = QPushButton("取消綁定")
        self.cancel_hotkey_btn.clicked.connect(self.cancel_hotkey_listen)
        self.cancel_hotkey_btn.hide()
        colors = get_theme_colors()
        self.cancel_hotkey_btn.setStyleSheet(f"background-color: {colors.error_bg}; color: white; border: none; padding: 5px;")
        
        self.adjust_icon_btn = QPushButton("調整圖標位置")
        self.adjust_icon_btn.clicked.connect(self.start_icon_adjustment)
        
        hotkey_layout.addWidget(self.hotkey_lbl)
        hotkey_layout.addWidget(self.set_hotkey_btn)
        hotkey_layout.addWidget(self.cancel_hotkey_btn)
        hotkey_layout.addWidget(self.adjust_icon_btn)
        main_layout.addLayout(hotkey_layout)

        # Start/Stop
        self.start_btn = QPushButton("▶ 啟動 PTT")
        self.start_btn.setFont(get_font(12, bold=True))
        self.start_btn.setStyleSheet(f"background-color: {colors.success_bg}; color: white; border: none;")
        self.start_btn.clicked.connect(self.toggle_ptt)
        self.start_btn.setFixedHeight(40)
        main_layout.addWidget(self.start_btn)

    def on_engine_changed(self, index):
        if index == 1:
            engine_type = 'voicemeeter'
        elif index == 2:
            engine_type = 'studioone'
        else:
            engine_type = 'windows'
            
        self.config.set('engine_type', engine_type)
        self.audio_manager.set_engine(engine_type)
        self.refresh_apps()

    def install_loopbe(self):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        installer_path = os.path.join(project_root, 'resources', 'setuploopbe1.exe')
        if os.path.exists(installer_path):
            try:
                import ctypes
                ctypes.windll.shell32.ShellExecuteW(None, "runas", installer_path, None, None, 1)
            except Exception:
                os.startfile(installer_path)
            QMessageBox.information(self, "提示", "已啟動 LoopBe1 安裝程式，請依照畫面指示按 Next 完成安裝。\n安裝完成後請點擊「🔄 重新整理 / 掃描」。")
        else:
            QMessageBox.warning(self, "錯誤", f"找不到安裝檔: {installer_path}")

    def run_diagnostic(self):
        log_path = self.audio_manager.generate_diagnostic()
        if log_path and os.path.exists(log_path):
            diag = DiagnosticDialog(self, log_path)
            diag.exec()
        else:
            QMessageBox.warning(self, "錯誤", "產生診斷報告失敗！")

    def refresh_apps(self):
        for w in self.app_widgets:
            self.scroll_layout.removeWidget(w)
            w.deleteLater()
        self.app_widgets.clear()

        struct = self.audio_manager.get_structure()
        colors = get_theme_colors()
        
        if struct['type'] == 'studioone_loopbe':
            self.matrix_frame.hide()
            self.refresh_btn.hide()
            self.scroll_area.show()
            self.s1_frame.show()
            
            port_name = struct.get('port_name', '')
            status = struct.get('status', 'ready')
            
            if status == 'ready':
                self.s1_status_lbl.setText(f"🟢 虛擬傳輸線已就緒 (已連線: {port_name})")
                self.s1_status_lbl.setStyleSheet(f"color: {colors.success};")
                self.s1_missing_box.hide()
                self.s1_btn_widget.show()
            else:
                self.s1_status_lbl.setText("⚠️ 尚未偵測到 LoopBe / MIDI 虛擬傳輸線")
                self.s1_status_lbl.setStyleSheet("color: #FFA500;")
                self.s1_missing_box.show()
                self.s1_btn_widget.hide()
            
            saved_signals = self.config.get('loopbe_signals')
            if saved_signals is None:
                # Default pre-filled 電腦觀眾 (CC 15) & 軌道 1 (CC 14)
                saved_signals = [
                    {
                        'id': 's1_cuemix_audience',
                        'name': '電腦觀眾 (CueMix 開關)',
                        'cc_num': 15,
                        'channel': 0,
                        'enabled': True
                    },
                    {
                        'id': 's1_track_1_mic',
                        'name': '軌道 1 (麥克風整軌)',
                        'cc_num': 14,
                        'channel': 0,
                        'enabled': False
                    }
                ]
                self.config.set('loopbe_signals', saved_signals)
                
            if not saved_signals:
                lbl = QLabel("目前尚未新增控制項目，請點擊上方的「➕ 新增控制項目」開始使用。")
                lbl.setAlignment(Qt.AlignCenter)
                self.scroll_layout.addWidget(lbl)
                self.app_widgets.append(lbl)
            else:
                for sig in saved_signals:
                    w = LoopBeSignalWidget(sig)
                    w.checkbox.stateChanged.connect(self.save_loopbe_signals)
                    w.test_btn.clicked.connect(lambda checked=False, s=sig: self.test_loopbe_signal(s))
                    w.edit_btn.clicked.connect(lambda checked=False, s=sig: self.edit_loopbe_signal(s))
                    w.delete_btn.clicked.connect(lambda checked=False, s=sig: self.delete_loopbe_signal(s))
                    self.scroll_layout.addWidget(w)
                    self.app_widgets.append(w)
                
        elif struct['type'] == 'matrix':
            self.refresh_btn.hide()
            self.s1_frame.hide()
            self.scroll_area.show()
            
            status = struct.get('status', 'ready')
            
            if status == 'missing_package':
                self.matrix_frame.hide()
                
                container = QWidget()
                layout = QVBoxLayout(container)
                layout.setAlignment(Qt.AlignCenter)
                layout.setSpacing(8)
                layout.setContentsMargins(10, 30, 10, 30)
                
                lbl_icon = QLabel("📦")
                lbl_icon.setFont(QFont("Segoe UI Emoji", 26))
                lbl_icon.setAlignment(Qt.AlignCenter)
                
                lbl_title = QLabel("❌ 尚未安裝 Voicemeeter Python 整合套件")
                lbl_title.setFont(get_font(11, bold=True))
                lbl_title.setStyleSheet(f"color: {colors.error};")
                lbl_title.setAlignment(Qt.AlignCenter)
                
                lbl_desc = QLabel("此模式需要「voicemeeter-api」套件以控制 Voicemeeter 路由。\n請點擊下方按鈕進行一鍵自動安裝。")
                lbl_desc.setFont(get_font(9))
                lbl_desc.setStyleSheet(f"color: {colors.text_dim};")
                lbl_desc.setAlignment(Qt.AlignCenter)
                
                btn_install = QPushButton("📥 一鍵安裝 voicemeeter-api 套件")
                btn_install.setFixedHeight(36)
                btn_install.setFont(get_font(10, bold=True))
                btn_install.setStyleSheet("background-color: #0078D4; color: white; border: none; border-radius: 5px; padding: 5px 20px;")
                btn_install.clicked.connect(lambda: self.install_voicemeeter_package(btn_install))
                
                layout.addWidget(lbl_icon)
                layout.addWidget(lbl_title)
                layout.addWidget(lbl_desc)
                layout.addSpacing(6)
                layout.addWidget(btn_install, alignment=Qt.AlignCenter)
                
                self.scroll_layout.addWidget(container)
                self.app_widgets.append(container)
                return
                
            elif status == 'app_not_running' or status == 'not_installed' or status == 'no_port':
                self.matrix_frame.hide()
                
                container = QWidget()
                layout = QVBoxLayout(container)
                layout.setAlignment(Qt.AlignCenter)
                layout.setSpacing(8)
                layout.setContentsMargins(10, 30, 10, 30)
                
                lbl_icon = QLabel("⚠️")
                lbl_icon.setFont(QFont("Segoe UI Emoji", 26))
                lbl_icon.setAlignment(Qt.AlignCenter)
                
                lbl_title = QLabel("voicemeeter-api 套件已就緒，但尚未連線到主程式")
                lbl_title.setFont(get_font(11, bold=True))
                lbl_title.setStyleSheet("color: #FFA500;")
                lbl_title.setAlignment(Qt.AlignCenter)
                
                lbl_desc = QLabel("請確認 Voicemeeter (Basic / Banana / Potato) 已開啟並正在背景執行。")
                lbl_desc.setFont(get_font(9))
                lbl_desc.setStyleSheet(f"color: {colors.text_dim};")
                lbl_desc.setAlignment(Qt.AlignCenter)
                
                btn_box = QHBoxLayout()
                btn_box.setAlignment(Qt.AlignCenter)
                
                btn_retry = QPushButton("🔄 重新連線")
                btn_retry.setFixedHeight(34)
                btn_retry.setFont(get_font(10, bold=True))
                btn_retry.setStyleSheet("background-color: #0078D4; color: white; border: none; border-radius: 5px; padding: 5px 15px;")
                btn_retry.clicked.connect(self.retry_voicemeeter_connect)
                
                btn_download = QPushButton("🌐 前往官網下載")
                btn_download.setFixedHeight(34)
                btn_download.setFont(get_font(10))
                btn_download.setStyleSheet(f"background-color: {colors.bg_card}; color: {colors.text_main}; border: 1px solid {colors.border}; border-radius: 5px; padding: 5px 15px;")
                btn_download.clicked.connect(lambda: os.startfile("https://vb-audio.com/Voicemeeter/"))
                
                btn_box.addWidget(btn_retry)
                btn_box.addWidget(btn_download)
                
                layout.addWidget(lbl_icon)
                layout.addWidget(lbl_title)
                layout.addWidget(lbl_desc)
                layout.addSpacing(6)
                layout.addLayout(btn_box)
                
                self.scroll_layout.addWidget(container)
                self.app_widgets.append(container)
                return
                
            else:
                self.matrix_frame.show()
            
            self.matrix_in_combo.clear()
            self.matrix_out_combo.clear()
            
            self.matrix_in_data = struct['inputs']
            self.matrix_out_data = struct['outputs']
            
            for item in self.matrix_in_data:
                self.matrix_in_combo.addItem(item['name'], userData=item['id'])
            for item in self.matrix_out_data:
                self.matrix_out_combo.addItem(item['name'], userData=item['id'])
                
            saved_devices = self.config.get('selected_apps') or []
            if not saved_devices:
                lbl = QLabel("請在上方選擇輸入與輸出端口，並點擊「➕ 新增路由控制」。")
                lbl.setAlignment(Qt.AlignCenter)
                self.scroll_layout.addWidget(lbl)
                self.app_widgets.append(lbl)
            else:
                for route_id in saved_devices:
                    parts = route_id.split('_')
                    if len(parts) == 3:
                        in_id = parts[1]
                        out_id = parts[2]
                        
                        in_name = next((x['name'] for x in self.matrix_in_data if x['id'] == in_id), f"Strip {in_id}")
                        out_name = next((x['name'] for x in self.matrix_out_data if x['id'] == out_id), f"{out_id}")
                        
                        app_info = {'id': route_id, 'name': f"{in_name} ➜ {out_name}"}
                        w = AppItemWidget(app_info)
                        w.checkbox.setChecked(True)
                        w.checkbox.stateChanged.connect(self.save_apps)
                        w.delete_btn.show()
                        
                        w.delete_btn.clicked.connect(lambda checked=False, rid=route_id: self.delete_matrix_route(rid))
                        self.scroll_layout.addWidget(w)
                        self.app_widgets.append(w)
                        
        else:
            self.matrix_frame.hide()
            self.s1_frame.hide()
            self.refresh_btn.show()
            self.scroll_area.show()
            
            devices = struct.get('items', [])
            if not devices:
                lbl = QLabel("目前沒有偵測到任何音效裝置")
                lbl.setAlignment(Qt.AlignCenter)
                self.scroll_layout.addWidget(lbl)
                self.app_widgets.append(lbl)
                return

            saved_devices = self.config.get('selected_apps') or []
            for app_info in devices:
                w = AppItemWidget(app_info)
                if app_info['id'] in saved_devices:
                    w.checkbox.setChecked(True)
                w.checkbox.stateChanged.connect(self.save_apps)
                self.scroll_layout.addWidget(w)
                self.app_widgets.append(w)

    def save_loopbe_signals(self):
        signals = self.config.get('loopbe_signals', [])
        for w in self.app_widgets:
            if isinstance(w, LoopBeSignalWidget):
                sig = w.signal_data
                sig['enabled'] = w.checkbox.isChecked()
                for i, s in enumerate(signals):
                    if s['id'] == sig['id']:
                        signals[i] = sig
                        break
        self.config.set('loopbe_signals', signals)

    def add_loopbe_signal(self):
        dialog = LoopBeSignalDialog(self)
        if dialog.exec() == QDialog.Accepted:
            new_sig = dialog.get_data()
            signals = self.config.get('loopbe_signals') or []
            signals.append(new_sig)
            self.config.set('loopbe_signals', signals)
            self.refresh_apps()

    def edit_loopbe_signal(self, sig):
        dialog = LoopBeSignalDialog(self, sig)
        if dialog.exec() == QDialog.Accepted:
            updated_sig = dialog.get_data()
            signals = self.config.get('loopbe_signals') or []
            for i, s in enumerate(signals):
                if s['id'] == updated_sig['id']:
                    signals[i] = updated_sig
                    break
            self.config.set('loopbe_signals', signals)
            self.refresh_apps()

    def delete_loopbe_signal(self, sig):
        reply = QMessageBox.question(self, "刪除", f"確定要刪除「{sig.get('name')}」嗎？", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            signals = self.config.get('loopbe_signals') or []
            signals = [s for s in signals if s['id'] != sig['id']]
            self.config.set('loopbe_signals', signals)
            self.refresh_apps()

    def test_loopbe_signal(self, sig):
        cc = sig.get('cc_num', 14)
        success, desc = self.audio_manager.send_test_signal(cc)
        if success:
            QMessageBox.information(
                self,
                "發送成功",
                f"✅ 已成功發送「{sig.get('name')}」測試訊號！\n{desc}\n\n"
                f"【Studio One 自動綁定提示】\n"
                f"只要在 Studio One 畫面點擊要綁定的按鈕（如 ⏻ 電腦觀眾 或 M 靜音），\n"
                f"然後點擊本測試按鈕，Studio One 就會自動捕捉並綁定此功能！"
            )
        else:
            QMessageBox.warning(self, "發送失敗", f"❌ 發送測試訊號失敗:\n{desc}")

    def open_studioone_guide(self):
        dialog = StudioOneGuideDialog(self)
        dialog.exec()

    def add_matrix_route(self):
        in_id = self.matrix_in_combo.currentData()
        out_id = self.matrix_out_combo.currentData()
        if in_id is None or out_id is None:
            return
            
        route_id = f"strip_{in_id}_{out_id}"
        saved = self.config.get('selected_apps') or []
        if route_id not in saved:
            saved.append(route_id)
            self.config.set('selected_apps', saved)
            self.refresh_apps()
            
    def delete_matrix_route(self, route_id):
        saved = self.config.get('selected_apps') or []
        if route_id in saved:
            saved.remove(route_id)
            self.config.set('selected_apps', saved)
            self.refresh_apps()

    def retry_voicemeeter_connect(self):
        engine = self.audio_manager.get_current_engine()
        if hasattr(engine, '_connect'):
            engine._connect()
        self.refresh_apps()

    def install_voicemeeter_package(self, btn):
        btn.setEnabled(False)
        btn.setText("⏳ 正在安裝 voicemeeter-api 套件...")
        
        self.pkg_worker = PackageInstallWorker("voicemeeter-api")
        def on_finished(success, msg):
            if success:
                QMessageBox.information(self, "安裝成功", "✅ 已成功安裝 voicemeeter-api 套件！\n即將自動連線至 Voicemeeter。")
                engine = self.audio_manager.get_current_engine()
                if hasattr(engine, '_connect'):
                    engine._connect()
                self.refresh_apps()
            else:
                QMessageBox.warning(self, "安裝失敗", f"❌ 安裝 voicemeeter-api 失敗:\n{msg}")
                btn.setEnabled(True)
                btn.setText("📥 一鍵安裝 voicemeeter-api 套件")
                
        self.pkg_worker.finished_signal.connect(on_finished)
        self.pkg_worker.start()

    def save_mode(self):
        mode = 'ptt' if self.mode_ptt_radio.isChecked() else 'toggle'
        self.config.set('mode', mode)

    def save_apps(self):
        selected_devices = []
        for w in self.app_widgets:
            if isinstance(w, AppItemWidget) and w.checkbox.isChecked():
                selected_devices.append(w.app_info['id'])
        self.config.set('selected_apps', selected_devices)

    def start_icon_adjustment(self):
        self.adjust_icon_btn.setText("請點擊左鍵放置圖標...")
        self.adjust_icon_btn.setEnabled(False)
        self.overlay.show()
        
        self.mover_thread = IconMoverThread()
        self.mover_thread.position_changed.connect(self.on_icon_moved)
        self.mover_thread.adjustment_finished.connect(self.on_icon_adjustment_finished)
        self.mover_thread.start()

    def on_icon_moved(self, x, y):
        self.overlay.move(x - 32, y - 32)

    def on_icon_adjustment_finished(self, x, y):
        final_x = x - 32
        final_y = y - 32
        self.overlay.move(final_x, final_y)
        self.config.set('icon_pos_x', final_x)
        self.config.set('icon_pos_y', final_y)
        
        if not self.ptt_worker.is_running or self.ptt_worker.is_active:
            self.overlay.hide()
            
        self.adjust_icon_btn.setText("調整圖標位置")
        self.adjust_icon_btn.setEnabled(True)
        self.mover_thread = None

    def start_hotkey_listen(self):
        self.set_hotkey_btn.setText("請按下組合鍵或滑鼠按鍵...")
        self.set_hotkey_btn.setEnabled(False)
        self.cancel_hotkey_btn.show()
        
        self.listener_thread = HotkeyRecorder()
        self.listener_thread.hotkey_detected.connect(self.on_hotkey_detected)
        self.listener_thread.start()

    def cancel_hotkey_listen(self):
        if self.listener_thread:
            self.listener_thread.cancel()
            self.listener_thread = None
            
        self.set_hotkey_btn.setText("設定快捷鍵")
        self.set_hotkey_btn.setEnabled(True)
        self.cancel_hotkey_btn.hide()

    def on_hotkey_detected(self, key_name):
        if key_name:
            self.hotkey = key_name
            self.hotkey_lbl.setText(f"目前快捷鍵: {self.hotkey}")
            self.config.set('hotkey', self.hotkey)
        self.cancel_hotkey_listen()

    def toggle_ptt(self):
        colors = get_theme_colors()
        if self.ptt_worker.is_running:
            self.ptt_worker.stop()
            self.overlay.hide()
            self.start_btn.setText("▶ 啟動 PTT")
            self.start_btn.setStyleSheet(f"background-color: {colors.success_bg}; color: white; border: none;")
            self.set_ui_enabled(True)
        else:
            if not self.hotkey:
                QMessageBox.warning(self, "錯誤", "請先設定快捷鍵！")
                return
            
            selected_devices = []
            for w in self.app_widgets:
                if isinstance(w, AppItemWidget) and w.checkbox.isChecked():
                    selected_devices.append(w.app_info['id'])
                elif isinstance(w, LoopBeSignalWidget) and w.checkbox.isChecked():
                    selected_devices.append(w.signal_data)
                    
            if not selected_devices:
                QMessageBox.warning(self, "錯誤", "請至少勾選一個裝置/訊號！")
                return

            mode = 'ptt' if self.mode_ptt_radio.isChecked() else 'toggle'
            if self.ptt_worker.start(self.hotkey, selected_devices, mode):
                self.overlay.show()
                self.start_btn.setText("⏹ 停止 PTT")
                self.start_btn.setStyleSheet(f"background-color: {colors.error_bg}; color: white; border: none;")
                self.set_ui_enabled(False)
            else:
                QMessageBox.warning(self, "錯誤", "啟動失敗！")

    def set_ui_enabled(self, enabled):
        self.engine_combo.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)
        self.set_hotkey_btn.setEnabled(enabled)
        self.mode_ptt_radio.setEnabled(enabled)
        self.mode_toggle_radio.setEnabled(enabled)
        
        if hasattr(self, 's1_add_btn'):
            self.s1_add_btn.setEnabled(enabled)
            self.s1_guide_btn.setEnabled(enabled)
            self.s1_diag_btn2.setEnabled(enabled)
        
        self.matrix_in_combo.setEnabled(enabled)
        self.matrix_out_combo.setEnabled(enabled)
        self.matrix_add_btn.setEnabled(enabled)
        
        for w in self.app_widgets:
            if isinstance(w, AppItemWidget):
                w.checkbox.setEnabled(enabled)
                w.delete_btn.setEnabled(enabled)
            elif isinstance(w, LoopBeSignalWidget):
                w.checkbox.setEnabled(enabled)
                w.test_btn.setEnabled(enabled)
                w.edit_btn.setEnabled(enabled)
                w.delete_btn.setEnabled(enabled)
                
    def on_ptt_state_changed(self, is_unmuted):
        self.overlay.set_state(is_unmuted)
            
    def closeEvent(self, event):
        if self.ptt_worker.is_running:
            self.ptt_worker.stop()
        if self.listener_thread:
            self.listener_thread.cancel()
        if self.mover_thread:
            self.mover_thread.cancel()
        self.overlay.close()
        self.audio_manager.cleanup()
        super().closeEvent(event)
