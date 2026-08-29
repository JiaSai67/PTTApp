import sys
import datetime
import socket
import struct
import ctypes

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QScrollArea, QCheckBox, 
                             QMessageBox, QApplication, QFileIconProvider,
                             QRadioButton, QButtonGroup, QComboBox,
                             QDialog, QFormLayout, QLineEdit, QListWidget,
                             QListWidgetItem, QTextEdit, QSpinBox)
from PySide6.QtCore import Qt, QThread, Signal, QFileInfo, QTimer
from PySide6.QtGui import QIcon, QFont, QColor
from pynput import keyboard, mouse

from src.core.audio_manager import AudioManager, encode_osc_message, decode_osc_message
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
        import subprocess
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
            return False # stop listener

    def _on_m_click(self, x, y, button, pressed):
        name = get_key_name(button)
        # 忽略滑鼠左鍵與右鍵，讓用戶可以點擊介面上的「取消」按鈕
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
                return False # Stop listener

    def cancel(self):
        self.running = False
        if self.m_listener: self.m_listener.stop()


class MidiSignalDialog(QDialog):
    def __init__(self, parent=None, signal_data=None):
        super().__init__(parent)
        self.setWindowTitle("新增/編輯 MIDI 訊號")
        self.setFixedSize(320, 140)
        self.signal_data = signal_data or {}
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        self.name_input = QLineEdit(self.signal_data.get('name', '新建功能'))
        form_layout.addRow("功能名稱:", self.name_input)
        layout.addLayout(form_layout)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("儲存")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
    def get_data(self):
        import uuid
        name = self.name_input.text().strip()
        if not name:
            name = "未命名功能"
            
        data = {
            'id': self.signal_data.get('id', str(uuid.uuid4())),
            'name': name,
            'enabled': self.signal_data.get('enabled', True)
        }
        
        if 'type' in self.signal_data:
            data['type'] = self.signal_data['type']
            data['channel'] = self.signal_data['channel']
            data['value'] = self.signal_data['value']
            
        return data

class MidiSignalWidget(QWidget):
    def __init__(self, signal_data):
        super().__init__()
        self.signal_data = signal_data
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        
        colors = get_theme_colors()
        self.setStyleSheet(f"background-color: {colors.bg_card}; color: {colors.text_main}; border-radius: 8px;")
        
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(signal_data.get('enabled', True))
        
        lbl_text = f"{signal_data.get('name', '')}  (內部代碼: CC {signal_data.get('value', 0)})"
        self.name_lbl = QLabel(lbl_text)
        self.name_lbl.setFont(get_font(10, bold=True))
        
        self.edit_btn = QPushButton("✏️ 編輯")
        self.edit_btn.setFixedSize(70, 28)
        self.edit_btn.setFont(get_font(9))
        self.edit_btn.setStyleSheet(f"background-color: #444; color: white; border: none; border-radius: 4px;")
        
        self.delete_btn = QPushButton("🗑️ 刪除")
        self.delete_btn.setFixedSize(60, 28)
        self.delete_btn.setFont(get_font(9))
        self.delete_btn.setStyleSheet(f"background-color: {colors.error_bg}; color: white; border: none; border-radius: 4px;")
        
        layout.addWidget(self.checkbox)
        layout.addSpacing(8)
        layout.addWidget(self.name_lbl, stretch=1)
        layout.addWidget(self.edit_btn)
        layout.addSpacing(4)
        layout.addWidget(self.delete_btn)


class OSCSignalDialog(QDialog):
    def __init__(self, parent=None, signal_data=None):
        super().__init__(parent)
        self.setWindowTitle("新增/編輯 Studio One OSC 軌道控制")
        self.setFixedSize(380, 220)
        self.signal_data = signal_data or {}
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("自訂設定 (Custom Address)")
        for i in range(1, 17):
            self.preset_combo.addItem(f"軌道 {i} (/track/{i}/mute)", f"/track/{i}/mute")
        self.preset_combo.addItem("主輸出總軌 (/main/mute)", "/main/mute")
        
        self.name_input = QLineEdit(self.signal_data.get('name', 'Track 1 麥克風軌道'))
        self.addr_input = QLineEdit(self.signal_data.get('address', '/track/1/mute'))
        
        self.type_combo = QComboBox()
        self.type_combo.addItem("Float 浮點數 (1.0 靜音 / 0.0 開麥 - Studio One 預設)", "float")
        self.type_combo.addItem("Int 整數 (1 靜音 / 0 開麥)", "int")
        self.type_combo.addItem("Bool 布林值 (True 靜音 / False 開麥)", "bool")
        
        if self.signal_data.get('type') == 'int':
            self.type_combo.setCurrentIndex(1)
        elif self.signal_data.get('type') == 'bool':
            self.type_combo.setCurrentIndex(2)
            
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        
        form_layout.addRow("快速範本:", self.preset_combo)
        form_layout.addRow("功能名稱:", self.name_input)
        form_layout.addRow("OSC 位址:", self.addr_input)
        form_layout.addRow("數值類型:", self.type_combo)
        layout.addLayout(form_layout)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("儲存")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
    def _on_preset_changed(self, idx):
        if idx > 0:
            addr = self.preset_combo.currentData()
            self.addr_input.setText(addr)
            if "main" in addr:
                self.name_input.setText("主輸出總軌 (Master)")
            else:
                parts = addr.split('/')
                track_num = parts[2] if len(parts) > 2 else "1"
                self.name_input.setText(f"Track {track_num} 麥克風軌道")

    def get_data(self):
        import uuid
        name = self.name_input.text().strip() or "未命名 OSC 軌道"
        addr = self.addr_input.text().strip() or "/track/1/mute"
        val_type = self.type_combo.currentData()
        
        return {
            'id': self.signal_data.get('id', str(uuid.uuid4())),
            'name': name,
            'address': addr,
            'type': val_type,
            'mute_val': 1.0 if val_type == 'float' else (1 if val_type == 'int' else True),
            'unmute_val': 0.0 if val_type == 'float' else (0 if val_type == 'int' else False),
            'enabled': self.signal_data.get('enabled', True)
        }

class OSCSignalWidget(QWidget):
    def __init__(self, signal_data):
        super().__init__()
        self.signal_data = signal_data
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        
        colors = get_theme_colors()
        self.setStyleSheet(f"background-color: {colors.bg_card}; color: {colors.text_main}; border-radius: 8px;")
        
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(signal_data.get('enabled', True))
        
        lbl_text = f"📡 {signal_data.get('name', '')}  (位址: {signal_data.get('address', '')})"
        self.name_lbl = QLabel(lbl_text)
        self.name_lbl.setFont(get_font(10, bold=True))
        
        self.edit_btn = QPushButton("✏️ 編輯")
        self.edit_btn.setFixedSize(70, 28)
        self.edit_btn.setFont(get_font(9))
        self.edit_btn.setStyleSheet(f"background-color: #444; color: white; border: none; border-radius: 4px;")
        
        self.delete_btn = QPushButton("🗑️ 刪除")
        self.delete_btn.setFixedSize(60, 28)
        self.delete_btn.setFont(get_font(9))
        self.delete_btn.setStyleSheet(f"background-color: {colors.error_bg}; color: white; border: none; border-radius: 4px;")
        
        layout.addWidget(self.checkbox)
        layout.addSpacing(8)
        layout.addWidget(self.name_lbl, stretch=1)
        layout.addWidget(self.edit_btn)
        layout.addSpacing(4)
        layout.addWidget(self.delete_btn)


class OSCConfigDialog(QDialog):
    def __init__(self, parent=None, config=None, audio_manager=None):
        super().__init__(parent)
        self.setWindowTitle("OSC 網路連線設定")
        self.setFixedSize(340, 160)
        self.config = config
        self.audio_manager = audio_manager
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        saved_ip = self.config.get('osc_ip') or "127.0.0.1"
        saved_port = str(self.config.get('osc_port') or 8000)
        
        self.ip_input = QLineEdit(saved_ip)
        self.port_input = QLineEdit(saved_port)
        
        form_layout.addRow("目標主機 (IP):", self.ip_input)
        form_layout.addRow("發送連接埠 (Port):", self.port_input)
        layout.addLayout(form_layout)
        
        tip_lbl = QLabel("💡 預設為 127.0.0.1:8000 (對應 Studio One 的 OSC 接收埠)")
        tip_lbl.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(tip_lbl)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("確認儲存")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
    def _on_save(self):
        ip = self.ip_input.text().strip() or "127.0.0.1"
        try:
            port = int(self.port_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "錯誤", "連接埠必須是有效的數字！(例如 8000)")
            return
            
        self.config.set('osc_ip', ip)
        self.config.set('osc_port', port)
        if self.audio_manager:
            engine = self.audio_manager.engines.get('studioone_osc')
            if engine and hasattr(engine, '_reload_config'):
                engine._reload_config()
        self.accept()


class OSCListenerWorker(QThread):
    msg_received = Signal(str, list)
    status_changed = Signal(str)

    def __init__(self, port=8000):
        super().__init__()
        self.port = port
        self.running = True
        self.sock = None

    def run(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(("0.0.0.0", self.port))
            self.sock.settimeout(0.5)
            self.status_changed.emit("監聽中 🟢")
        except Exception as e:
            self.status_changed.emit(f"綁定失敗 ({e}) 🔴")
            return

        while self.running:
            try:
                data, addr = self.sock.recvfrom(2048)
                if data:
                    osc_addr, args = decode_osc_message(data)
                    self.msg_received.emit(osc_addr, args)
            except socket.timeout:
                continue
            except Exception:
                break

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


class MIDIListenerWorker(QThread):
    msg_received = Signal(str)
    status_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.hMidiIn = None

    def run(self):
        winmm = ctypes.windll.winmm
        num_in = winmm.midiInGetNumDevs()
        if num_in == 0:
            self.status_changed.emit("無輸入裝置 ⚪")
            return
            
        MIM_DATA = 0x3C3
        MIDIINPROC = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t)

        def _cb(hMidiIn, wMsg, dwInstance, dwParam1, dwParam2):
            if wMsg == MIM_DATA:
                status = dwParam1 & 0xFF
                data1 = (dwParam1 >> 8) & 0xFF
                data2 = (dwParam1 >> 16) & 0xFF
                
                msg_type = "未知"
                if (status & 0xF0) == 0xB0:
                    ch = status & 0x0F
                    msg_type = f"CC 控制 (Ch:{ch}, CC:{data1}, Val:{data2})"
                elif (status & 0xF0) == 0x90:
                    ch = status & 0x0F
                    msg_type = f"Note ON (Ch:{ch}, Note:{data1}, Vel:{data2})"
                elif (status & 0xF0) == 0x80:
                    ch = status & 0x0F
                    msg_type = f"Note OFF (Ch:{ch}, Note:{data1}, Vel:{data2})"
                    
                self.msg_received.emit(f"Status=0x{status:02X} -> {msg_type}")

        self.cb_func = MIDIINPROC(_cb)
        hIn = ctypes.c_void_p()
        res = winmm.midiInOpen(ctypes.byref(hIn), 0, self.cb_func, 0, 0x00030000)
        if res == 0:
            self.hMidiIn = hIn
            winmm.midiInStart(hIn)
            self.status_changed.emit("監聽中 🟢")
            while self.running:
                self.msleep(100)
            winmm.midiInStop(hIn)
            winmm.midiInClose(hIn)
        else:
            self.status_changed.emit(f"開啟失敗 (代碼:{res}) 🔴")

    def stop(self):
        self.running = False


class SignalMonitorDialog(QDialog):
    def __init__(self, parent=None, config=None, audio_manager=None):
        super().__init__(parent)
        self.setWindowTitle("🔍 PTTApp 即時訊號監聽與模擬測試器")
        self.resize(580, 440)
        self.config = config
        self.audio_manager = audio_manager
        
        self.osc_listener = None
        self.midi_listener = None
        
        layout = QVBoxLayout(self)
        colors = get_theme_colors()
        
        # Status header
        status_box = QHBoxLayout()
        self.osc_status_tag = QLabel("📡 OSC 監聽器: 啟動中...")
        self.osc_status_tag.setStyleSheet(f"color: {colors.success}; font-weight: bold;")
        self.midi_status_tag = QLabel("🎹 MIDI 監聽器: 啟動中...")
        self.midi_status_tag.setStyleSheet(f"color: {colors.success}; font-weight: bold;")
        status_box.addWidget(self.osc_status_tag)
        status_box.addWidget(self.midi_status_tag)
        layout.addLayout(status_box)
        
        # Log list
        self.log_list = QListWidget()
        self.log_list.setFont(QFont("Consolas", 10))
        self.log_list.setStyleSheet(f"background-color: {colors.bg_card}; color: {colors.text_main}; border: 1px solid {colors.border}; border-radius: 6px;")
        layout.addWidget(self.log_list)
        
        # Action triggers
        btn_layout = QHBoxLayout()
        
        btn_unmute = QPushButton("⚡ 模擬發話 (取消靜音)")
        btn_unmute.setStyleSheet(f"background-color: {colors.success_bg}; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold;")
        btn_unmute.clicked.connect(self._trigger_unmute)
        
        btn_mute = QPushButton("🔇 模擬放開 (恢復靜音)")
        btn_mute.setStyleSheet(f"background-color: {colors.error_bg}; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold;")
        btn_mute.clicked.connect(self._trigger_mute)
        
        btn_clear = QPushButton("🧹 清除紀錄")
        btn_clear.clicked.connect(self.log_list.clear)
        
        btn_layout.addWidget(btn_unmute)
        btn_layout.addWidget(btn_mute)
        btn_layout.addWidget(btn_clear)
        layout.addLayout(btn_layout)
        
        self.start_listeners()
        self.add_log("系統", "即時訊號監聽與模擬測試器已就緒，等待訊號傳入...")

    def add_log(self, tag, text, color=None):
        now_str = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        item_text = f"[{now_str}] [{tag}] {text}"
        item = QListWidgetItem(item_text)
        if color:
            item.setForeground(QColor(color))
        self.log_list.addItem(item)
        self.log_list.scrollToBottom()

    def start_listeners(self):
        # 1. OSC UDP Server
        port = int(self.config.get('osc_port') or 8000)
        self.osc_listener = OSCListenerWorker(port)
        self.osc_listener.msg_received.connect(lambda addr, args: self.add_log("OSC 接收", f"{addr} -> {args}", "#6CCB5F"))
        self.osc_listener.status_changed.connect(lambda s: self.osc_status_tag.setText(f"📡 OSC ({port}): {s}"))
        self.osc_listener.start()
        
        # 2. MIDI In loopback
        self.midi_listener = MIDIListenerWorker()
        self.midi_listener.msg_received.connect(lambda desc: self.add_log("MIDI 接收", desc, "#6CCB5F"))
        self.midi_listener.status_changed.connect(lambda s: self.midi_status_tag.setText(f"🎹 MIDI: {s}"))
        self.midi_listener.start()

    def _trigger_unmute(self):
        self.add_log("PTT 動作", "觸發【發話】訊號 (取消靜音)...", "#FFA500")
        if self.audio_manager:
            engine_type = self.audio_manager.engine_type
            if engine_type == 'studioone_osc':
                sigs = self.config.get('osc_signals') or [{'address': '/track/1/mute'}]
                self.audio_manager.set_mute_for_devices(sigs, mute=False)
            elif engine_type == 'studioone':
                sigs = self.config.get('midi_signals') or [{'type': 'cc', 'channel': 0, 'value': 14}]
                self.audio_manager.set_mute_for_devices(sigs, mute=False)
            else:
                self.audio_manager.send_test_signal()

    def _trigger_mute(self):
        self.add_log("PTT 動作", "觸發【放開】訊號 (恢復靜音)...", "#FF99A4")
        if self.audio_manager:
            engine_type = self.audio_manager.engine_type
            if engine_type == 'studioone_osc':
                sigs = self.config.get('osc_signals') or [{'address': '/track/1/mute'}]
                self.audio_manager.set_mute_for_devices(sigs, mute=True)
            elif engine_type == 'studioone':
                sigs = self.config.get('midi_signals') or [{'type': 'cc', 'channel': 0, 'value': 14}]
                self.audio_manager.set_mute_for_devices(sigs, mute=True)
            else:
                self.audio_manager.set_mute_for_devices([], mute=True)

    def closeEvent(self, event):
        if self.osc_listener:
            self.osc_listener.stop()
        if self.midi_listener:
            self.midi_listener.stop()
        super().closeEvent(event)


class AppItemWidget(QWidget):
    def __init__(self, app_info):
        super().__init__()
        self.app_info = app_info
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        colors = get_theme_colors()
        self.setStyleSheet(f"background-color: {colors.bg_card}; color: {colors.text_main}; border-radius: 5px;")

        # Checkbox
        self.checkbox = QCheckBox()
        layout.addWidget(self.checkbox)
        
        # Icon (Fallback mic icon since these are devices)
        self.icon_label = QLabel("🎤")
        self.icon_label.setFont(QFont("Segoe UI Emoji", 14))
        layout.addWidget(self.icon_label)
        
        # Name
        self.name_label = QLabel(app_info['name'])
        self.name_label.setFont(get_font(10))
        layout.addWidget(self.name_label)
        
        layout.addStretch()

        # Delete button for matrix routes (optional, hidden by default)
        self.delete_btn = QPushButton("🗑️")
        self.delete_btn.setFixedSize(30, 30)
        self.delete_btn.setStyleSheet("background: transparent; border: none;")
        self.delete_btn.hide()
        layout.addWidget(self.delete_btn)


VERSION = "1.1.2"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"按鍵發話 (PTT) 控制器 v{VERSION}")
VERSION = "1.2.0"

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
        self.midi_status = None
        
        # Continuous background poll timer for MIDI state changes
        self.midi_poll_timer = QTimer(self)
        self.midi_poll_timer.timeout.connect(self.poll_midi_status)
        
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
            "Windows 系統麥克風 (目前模式)",
            "Voicemeeter 路由控制",
            "Studio One (OSC 免驅動模式 - 推薦)",
            "Studio One (MIDI 模式 - loopMIDI)"
        ])
        saved_engine = self.config.get('engine_type') or 'windows'
        if saved_engine == 'voicemeeter':
            self.engine_combo.setCurrentIndex(1)
        elif saved_engine == 'studioone_osc':
            self.engine_combo.setCurrentIndex(2)
        elif saved_engine == 'studioone':
            self.engine_combo.setCurrentIndex(3)
            self.midi_poll_timer.start(1000)
        else:
            self.engine_combo.setCurrentIndex(0)
            
        self.audio_manager.set_engine(saved_engine)
        self.engine_combo.currentIndexChanged.connect(self.on_engine_changed)
        
        header_layout.addWidget(header_lbl)
        header_layout.addWidget(self.engine_combo)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        # Matrix Controls (hidden by default, shown for Voicemeeter)
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
        
        # OSC Controls (hidden by default, shown for Studio One OSC)
        self.osc_frame = QWidget()
        osc_layout = QVBoxLayout(self.osc_frame)
        osc_layout.setContentsMargins(0, 0, 0, 4)
        osc_layout.setSpacing(4)
        
        self.osc_status_lbl = QLabel()
        self.osc_status_lbl.setFont(get_font(10, bold=True))
        self.osc_status_lbl.setAlignment(Qt.AlignCenter)
        
        self.osc_guide_lbl = QLabel("💡 Studio One 設定：選項 ➜ 外部裝置 ➜ 新增 Open Sound Control ➜ 接收埠設為 8000")
        self.osc_guide_lbl.setFont(get_font(8))
        self.osc_guide_lbl.setAlignment(Qt.AlignCenter)
        self.osc_guide_lbl.setStyleSheet("color: #888;")
        
        self.osc_btn_widget = QWidget()
        osc_btn_layout = QHBoxLayout(self.osc_btn_widget)
        osc_btn_layout.setContentsMargins(0, 0, 0, 0)
        osc_btn_layout.setSpacing(6)
        
        self.osc_add_btn = QPushButton("➕ 新增 OSC 軌道")
        self.osc_add_btn.setFixedHeight(30)
        self.osc_add_btn.clicked.connect(self.add_osc_signal)
        
        self.osc_test_btn = QPushButton("⚡ 測試訊號")
        self.osc_test_btn.setFixedHeight(30)
        self.osc_test_btn.clicked.connect(self.send_test_osc)
        
        self.osc_monitor_btn = QPushButton("🔍 訊號監聽模擬器")
        self.osc_monitor_btn.setFixedHeight(30)
        self.osc_monitor_btn.clicked.connect(self.open_signal_monitor)
        
        self.osc_config_btn = QPushButton("⚙️ 連接埠設定")
        self.osc_config_btn.setFixedHeight(30)
        self.osc_config_btn.clicked.connect(self.open_osc_config)
        
        osc_btn_layout.addWidget(self.osc_add_btn)
        osc_btn_layout.addWidget(self.osc_test_btn)
        osc_btn_layout.addWidget(self.osc_monitor_btn)
        osc_btn_layout.addWidget(self.osc_config_btn)
        
        osc_layout.addWidget(self.osc_status_lbl)
        osc_layout.addWidget(self.osc_guide_lbl)
        osc_layout.addWidget(self.osc_btn_widget)
        
        self.osc_frame.hide()
        main_layout.addWidget(self.osc_frame)

        # MIDI Controls (hidden by default, shown for Studio One MIDI)
        self.midi_frame = QWidget()
        midi_layout = QVBoxLayout(self.midi_frame)
        midi_layout.setContentsMargins(0, 0, 0, 4)
        midi_layout.setSpacing(4)
        
        self.midi_status_lbl = QLabel()
        self.midi_status_lbl.setFont(get_font(10, bold=True))
        self.midi_status_lbl.setAlignment(Qt.AlignCenter)
        self.midi_status_lbl.setWordWrap(True)
        
        self.midi_action_btn = QPushButton()
        self.midi_action_btn.setFont(get_font(10, bold=True))
        self.midi_action_btn.setFixedSize(260, 34)
        self.midi_action_btn.clicked.connect(self.handle_midi_action)
        
        self.midi_btn_widget = QWidget()
        btn_layout = QHBoxLayout(self.midi_btn_widget)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(6)
        
        self.midi_add_btn = QPushButton("➕ 新增訊號")
        self.midi_add_btn.setFixedHeight(30)
        self.midi_add_btn.clicked.connect(self.add_midi_signal)
        
        self.midi_test_btn = QPushButton("⚡ 測試訊號")
        self.midi_test_btn.setFixedHeight(30)
        self.midi_test_btn.clicked.connect(self.send_test_midi)
        
        self.midi_monitor_btn = QPushButton("🔍 訊號監聽器")
        self.midi_monitor_btn.setFixedHeight(30)
        self.midi_monitor_btn.clicked.connect(self.open_signal_monitor)
        
        self.midi_diag_btn = QPushButton("🛠️ 診斷報告")
        self.midi_diag_btn.setFixedHeight(30)
        self.midi_diag_btn.clicked.connect(self.run_midi_diagnostic)
        
        btn_layout.addWidget(self.midi_add_btn)
        btn_layout.addWidget(self.midi_test_btn)
        btn_layout.addWidget(self.midi_monitor_btn)
        btn_layout.addWidget(self.midi_diag_btn)
        
        midi_layout.addWidget(self.midi_status_lbl)
        midi_layout.addWidget(self.midi_action_btn, alignment=Qt.AlignCenter)
        midi_layout.addWidget(self.midi_btn_widget)
        
        self.midi_frame.hide()
        main_layout.addWidget(self.midi_frame)

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
        colors = get_theme_colors()
        self.start_btn.setStyleSheet(f"background-color: {colors.success_bg}; color: white; border: none;")
        self.start_btn.clicked.connect(self.toggle_ptt)
        self.start_btn.setFixedHeight(40)
        main_layout.addWidget(self.start_btn)

    def on_engine_changed(self, index):
        if index == 1:
            engine_type = 'voicemeeter'
            self.midi_poll_timer.stop()
        elif index == 2:
            engine_type = 'studioone_osc'
            self.midi_poll_timer.stop()
        elif index == 3:
            engine_type = 'studioone'
            self.midi_poll_timer.start(1000)
        else:
            engine_type = 'windows'
            self.midi_poll_timer.stop()
            
        self.config.set('engine_type', engine_type)
        self.audio_manager.set_engine(engine_type)
        self.refresh_apps()

    def poll_midi_status(self):
        """Continuous live check of MIDI connection state"""
        if self.config.get('engine_type') != 'studioone':
            return
            
        struct = self.audio_manager.get_structure()
        new_status = struct.get('status')
        if new_status != self.midi_status:
            self.refresh_apps()

    def refresh_apps(self):
        # Clear old
        for w in self.app_widgets:
            self.scroll_layout.removeWidget(w)
            w.deleteLater()
        self.app_widgets.clear()

        struct = self.audio_manager.get_structure()
        colors = get_theme_colors()
        
        if struct['type'] == 'osc':
            self.matrix_frame.hide()
            self.midi_frame.hide()
            self.refresh_btn.hide()
            self.scroll_area.show()
            self.osc_frame.show()
            
            ip = struct.get('ip', '127.0.0.1')
            port = struct.get('port', 8000)
            self.osc_status_lbl.setText(f"🟢 OSC 免驅動模式已就緒 (發送目標: {ip}:{port})")
            self.osc_status_lbl.setStyleSheet(f"color: {colors.success};")
            
            saved_signals = self.config.get('osc_signals')
            if saved_signals is None:
                saved_signals = [{
                    'id': 'osc_track_1',
                    'name': 'Track 1 麥克風軌道',
                    'address': '/track/1/mute',
                    'type': 'float',
                    'mute_val': 1.0,
                    'unmute_val': 0.0,
                    'enabled': True
                }]
                self.config.set('osc_signals', saved_signals)
                
            if not saved_signals:
                lbl = QLabel("請點選上方的「➕ 新增 OSC 軌道」按鈕開始綁定。")
                lbl.setAlignment(Qt.AlignCenter)
                self.scroll_layout.addWidget(lbl)
                self.app_widgets.append(lbl)
            else:
                for sig in saved_signals:
                    w = OSCSignalWidget(sig)
                    w.checkbox.stateChanged.connect(self.save_osc_signals)
                    w.edit_btn.clicked.connect(lambda checked=False, s=sig: self.edit_osc_signal(s))
                    w.delete_btn.clicked.connect(lambda checked=False, s=sig: self.delete_osc_signal(s))
                    self.scroll_layout.addWidget(w)
                    self.app_widgets.append(w)
                    
        elif struct['type'] == 'midi':
            self.matrix_frame.hide()
            self.osc_frame.hide()
            self.refresh_btn.hide()
            self.scroll_area.show()
            self.midi_frame.show()
            
            self.midi_status = struct.get('status', 'not_installed')
            devices = struct.get('devices', [])
            port_name = struct.get('port_name', '')
            
            if self.midi_status == 'ready':
                self.midi_status_lbl.setText(f"🟢 loopMIDI 虛擬線已就緒 (已連線: {port_name})")
                self.midi_status_lbl.setStyleSheet(f"color: {colors.success};")
                self.midi_action_btn.hide()
                self.midi_btn_widget.show()
            elif self.midi_status == 'locked':
                self.midi_status_lbl.setText("⚠️ MIDI 連接埠被佔用！請確認 Studio One「發送到」設為『無』")
                self.midi_status_lbl.setStyleSheet(f"color: {colors.error};")
                self.midi_action_btn.setText("🔄 修正完畢，點我重新連線")
                self.midi_action_btn.setStyleSheet(f"background-color: #0078D4; color: white; border: none; border-radius: 5px;")
                self.midi_action_btn.show()
                self.midi_btn_widget.hide()
            elif self.midi_status == 'no_port':
                is_adm = struct.get('is_admin', False)
                lm_running = struct.get('loopmidi_running', False)
                dev_desc = ", ".join(devices) if devices else "無可見裝置"
                
                if lm_running and is_adm:
                    self.midi_status_lbl.setText(
                        f"⚠️ 偵測到 Windows 權限隔離或連接埠未同步！\n"
                        f"PTTApp 目前以「系統管理員」身分執行。\n"
                        f"1. 請在 loopMIDI 點擊 [-] 刪除再按 [+] 重新新增連接埠。\n"
                        f"2. 或點擊下方按鈕以管理員身分重啟 loopMIDI。"
                    )
                    self.midi_action_btn.setText("🚀 重新以管理員身分啟動 loopMIDI")
                elif lm_running:
                    self.midi_status_lbl.setText("⚠️ loopMIDI 執行中但尚未偵測到連接埠，請點擊 [+] 新增。")
                    self.midi_action_btn.setText("🚀 開啟 loopMIDI 介面")
                else:
                    self.midi_status_lbl.setText(f"⚠️ 尚未偵測到可用虛擬線 (可見: {dev_desc})")
                    self.midi_action_btn.setText("🚀 啟動 loopMIDI")

                self.midi_status_lbl.setStyleSheet(f"color: #FFA500;")
                self.midi_action_btn.setStyleSheet(f"background-color: #0078D4; color: white; border: none; border-radius: 5px;")
                self.midi_action_btn.show()
                self.midi_btn_widget.hide()
            else:
                self.midi_status_lbl.setText("❌ 尚未安裝 loopMIDI 驅動\n請點擊下方按鈕進行一鍵安裝")
                self.midi_status_lbl.setStyleSheet(f"color: {colors.error};")
                self.midi_action_btn.setText("📥 一鍵安裝 loopMIDI")
                self.midi_action_btn.setStyleSheet(f"background-color: #0078D4; color: white; border: none; border-radius: 5px;")
                self.midi_action_btn.show()
                self.midi_btn_widget.hide()
                
            saved_signals = self.config.get('midi_signals', [])
            if not saved_signals and self.midi_status == 'ready':
                lbl = QLabel("請點選上方的「新增 MIDI 訊號」按鈕開始綁定。")
                lbl.setAlignment(Qt.AlignCenter)
                self.scroll_layout.addWidget(lbl)
                self.app_widgets.append(lbl)
            else:
                for sig in saved_signals:
                    w = MidiSignalWidget(sig)
                    w.checkbox.stateChanged.connect(self.save_midi_signals)
                    w.edit_btn.clicked.connect(lambda checked=False, s=sig: self.edit_midi_signal(s))
                    w.delete_btn.clicked.connect(lambda checked=False, s=sig: self.delete_midi_signal(s))
                    self.scroll_layout.addWidget(w)
                    self.app_widgets.append(w)
                
        elif struct['type'] == 'matrix':
            self.refresh_btn.hide()
            self.midi_frame.hide()
            self.osc_frame.hide()
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
            
            # Update comboboxes
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
            self.midi_frame.hide()
            self.osc_frame.hide()
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

    def save_osc_signals(self):
        signals = self.config.get('osc_signals', [])
        for w in self.app_widgets:
            if isinstance(w, OSCSignalWidget):
                sig = w.signal_data
                sig['enabled'] = w.checkbox.isChecked()
                for i, s in enumerate(signals):
                    if s['id'] == sig['id']:
                        signals[i] = sig
                        break
        self.config.set('osc_signals', signals)

    def add_osc_signal(self):
        dialog = OSCSignalDialog(self)
        if dialog.exec() == QDialog.Accepted:
            new_sig = dialog.get_data()
            signals = self.config.get('osc_signals') or []
            signals.append(new_sig)
            self.config.set('osc_signals', signals)
            self.refresh_apps()

    def edit_osc_signal(self, sig):
        dialog = OSCSignalDialog(self, sig)
        if dialog.exec() == QDialog.Accepted:
            updated_sig = dialog.get_data()
            signals = self.config.get('osc_signals') or []
            for i, s in enumerate(signals):
                if s['id'] == updated_sig['id']:
                    signals[i] = updated_sig
                    break
            self.config.set('osc_signals', signals)
            self.refresh_apps()

    def delete_osc_signal(self, sig):
        reply = QMessageBox.question(self, "刪除", f"確定要刪除「{sig.get('name')}」嗎？", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            signals = self.config.get('osc_signals') or []
            signals = [s for s in signals if s['id'] != sig['id']]
            self.config.set('osc_signals', signals)
            self.refresh_apps()

    def send_test_osc(self):
        success, desc = self.audio_manager.send_test_signal()
        if success:
            QMessageBox.information(
                self,
                "發送成功",
                f"✅ 已成功發送 OSC 測試訊號！\n{desc}\n\n"
                f"Studio One 若已新增 Open Sound Control 外部裝置並設為接收埠 8000，\n"
                f"軌道上的靜音 (Mute) 燈號將會閃爍一次。"
            )
        else:
            QMessageBox.warning(self, "發送失敗", f"❌ 發送 OSC 測試訊號失敗:\n{desc}")

    def open_osc_config(self):
        dialog = OSCConfigDialog(self, self.config, self.audio_manager)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_apps()

    def open_signal_monitor(self):
        dialog = SignalMonitorDialog(self, self.config, self.audio_manager)
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

    def handle_midi_action(self):
        import os
        import subprocess
        import ctypes
        
        if self.midi_status == 'locked':
            self.refresh_apps()
        elif self.midi_status == 'not_installed':
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            installer_path = os.path.join(project_root, 'resources', 'loopMIDISetup.exe')
            if os.path.exists(installer_path):
                os.startfile(installer_path)
            else:
                QMessageBox.warning(self, "錯誤", f"找不到安裝檔，尋找路徑為: {installer_path}")
        elif self.midi_status == 'no_port':
            loopmidi_path = r"C:\Program Files (x86)\Tobias Erichsen\loopMIDI\loopMIDI.exe"
            if os.path.exists(loopmidi_path):
                try:
                    subprocess.run('taskkill /F /IM loopMIDI.exe', shell=True, capture_output=True)
                    engine = self.audio_manager.get_current_engine()
                    if hasattr(engine, 'is_admin') and engine.is_admin():
                        ctypes.windll.shell32.ShellExecuteW(None, "runas", loopmidi_path, None, None, 1)
                    else:
                        os.startfile(loopmidi_path)
                except Exception:
                    subprocess.Popen(loopmidi_path, shell=True)
            self.refresh_apps()
        else:
            QMessageBox.information(self, "提示", "請在即將開啟的視窗中找到「loopMIDI」，點擊解除安裝。")
            subprocess.Popen("appwiz.cpl", shell=True)

    def run_midi_diagnostic(self):
        import os
        import subprocess
        log_path = self.audio_manager.generate_midi_diagnostic()
        if log_path and os.path.exists(log_path):
            QMessageBox.information(self, "檢測完成", f"已產生檢測報告於:\n{log_path}\n\n即將為您開啟該檔案。")
            subprocess.Popen(['notepad.exe', log_path])
        else:
            QMessageBox.warning(self, "錯誤", "產生檢測報告失敗，請確認程式是否有寫入權限。")

    def send_test_midi(self):
        success, desc = self.audio_manager.send_test_signal()
        if success:
            QMessageBox.information(
                self,
                "發送成功",
                f"✅ 已成功發送 MIDI 測試訊號！\n{desc}\n\n"
                f"請檢查：\n"
                f"1. loopMIDI 視窗中的 Total data 是否有增加。\n"
                f"2. Studio One 的 MIDI 學習面板是否有捕捉到按鈕。"
            )
        else:
            QMessageBox.warning(self, "發送失敗", f"❌ 發送 MIDI 測試訊號失敗:\n{desc}")

    def save_mode(self):
        mode = 'ptt' if self.mode_ptt_radio.isChecked() else 'toggle'
        self.config.set('mode', mode)

    def save_apps(self):
        selected_devices = []
        for w in self.app_widgets:
            if isinstance(w, AppItemWidget) and w.checkbox.isChecked():
                selected_devices.append(w.app_info['id'])
        self.config.set('selected_apps', selected_devices)

    def save_midi_signals(self):
        signals = self.config.get('midi_signals', [])
        for w in self.app_widgets:
            if isinstance(w, MidiSignalWidget):
                sig = w.signal_data
                sig['enabled'] = w.checkbox.isChecked()
                for i, s in enumerate(signals):
                    if s['id'] == sig['id']:
                        signals[i] = sig
                        break
        self.config.set('midi_signals', signals)
        
    def add_midi_signal(self):
        dialog = MidiSignalDialog(self)
        if dialog.exec() == QDialog.Accepted:
            new_sig = dialog.get_data()
            signals = self.config.get('midi_signals', [])
            
            # Auto-assign unique CC value
            used_vals = [s.get('value', 0) for s in signals if s.get('type', 'cc') == 'cc']
            next_val = 14
            while next_val in used_vals:
                next_val += 1
                
            new_sig['type'] = 'cc'
            new_sig['channel'] = 0
            new_sig['value'] = next_val
            
            signals.append(new_sig)
            self.config.set('midi_signals', signals)
            self.refresh_apps()
            
    def edit_midi_signal(self, sig):
        dialog = MidiSignalDialog(self, sig)
        if dialog.exec() == QDialog.Accepted:
            updated_sig = dialog.get_data()
            signals = self.config.get('midi_signals', [])
            for i, s in enumerate(signals):
                if s['id'] == updated_sig['id']:
                    signals[i] = updated_sig
                    break
            self.config.set('midi_signals', signals)
            self.refresh_apps()
            
    def delete_midi_signal(self, sig):
        reply = QMessageBox.question(self, "刪除", f"確定要刪除「{sig.get('name')}」嗎？", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            signals = self.config.get('midi_signals', [])
            signals = [s for s in signals if s['id'] != sig['id']]
            self.config.set('midi_signals', signals)
            self.refresh_apps()

    def start_icon_adjustment(self):
        self.adjust_icon_btn.setText("請點擊左鍵放置圖標...")
        self.adjust_icon_btn.setEnabled(False)
        self.overlay.show()
        
        self.mover_thread = IconMoverThread()
        self.mover_thread.position_changed.connect(self.on_icon_moved)
        self.mover_thread.adjustment_finished.connect(self.on_icon_adjustment_finished)
        self.mover_thread.start()

    def on_icon_moved(self, x, y):
        # Center the icon (64x64) on the mouse pointer
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
                elif isinstance(w, MidiSignalWidget) and w.checkbox.isChecked():
                    selected_devices.append(w.signal_data)
                elif isinstance(w, OSCSignalWidget) and w.checkbox.isChecked():
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
        
        # OSC toolbar lock
        if hasattr(self, 'osc_add_btn'):
            self.osc_add_btn.setEnabled(enabled)
            self.osc_test_btn.setEnabled(enabled)
            self.osc_monitor_btn.setEnabled(enabled)
            self.osc_config_btn.setEnabled(enabled)

        # MIDI toolbar lock
        self.midi_add_btn.setEnabled(enabled)
        self.midi_test_btn.setEnabled(enabled)
        if hasattr(self, 'midi_monitor_btn'):
            self.midi_monitor_btn.setEnabled(enabled)
        self.midi_rescan_btn.setEnabled(enabled)
        self.midi_diag_btn.setEnabled(enabled)
        self.midi_action_btn.setEnabled(enabled)
        
        # Matrix controls lock
        self.matrix_in_combo.setEnabled(enabled)
        self.matrix_out_combo.setEnabled(enabled)
        self.matrix_add_btn.setEnabled(enabled)
        
        # All items lock (Checkboxes, Edit buttons, Delete buttons)
        for w in self.app_widgets:
            if isinstance(w, AppItemWidget):
                w.checkbox.setEnabled(enabled)
                w.delete_btn.setEnabled(enabled)
            elif isinstance(w, MidiSignalWidget):
                w.checkbox.setEnabled(enabled)
                w.edit_btn.setEnabled(enabled)
                w.delete_btn.setEnabled(enabled)
            elif isinstance(w, OSCSignalWidget):
                w.checkbox.setEnabled(enabled)
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
