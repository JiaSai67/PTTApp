import sys
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QScrollArea, QCheckBox, 
                             QMessageBox, QApplication, QFileIconProvider,
                             QRadioButton, QButtonGroup, QComboBox)
from PySide6.QtCore import Qt, QThread, Signal, QFileInfo, QTimer
from PySide6.QtGui import QIcon, QFont
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
        self.setFixedSize(350, 250)
        self.signal_data = signal_data or {}
        
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        
        self.name_input = QLineEdit(self.signal_data.get('name', '新建訊號'))
        form_layout.addRow("名稱:", self.name_input)
        
        self.type_combo = QComboBox()
        self.type_combo.addItems(["CC (Control Change)", "Note (音符)"])
        if self.signal_data.get('type') == 'note':
            self.type_combo.setCurrentIndex(1)
        form_layout.addRow("類型:", self.type_combo)
        
        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(1, 16)
        self.channel_spin.setValue(self.signal_data.get('channel', 0) + 1)
        form_layout.addRow("通道 (1-16):", self.channel_spin)
        
        self.val_spin = QSpinBox()
        self.val_spin.setRange(0, 127)
        self.val_spin.setValue(self.signal_data.get('value', 14))
        form_layout.addRow("控制碼/音符號碼:", self.val_spin)
        
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
        return {
            'id': self.signal_data.get('id', str(uuid.uuid4())),
            'name': self.name_input.text(),
            'type': 'note' if self.type_combo.currentIndex() == 1 else 'cc',
            'channel': self.channel_spin.value() - 1,
            'value': self.val_spin.value(),
            'enabled': self.signal_data.get('enabled', True)
        }

class MidiSignalWidget(QWidget):
    def __init__(self, signal_data):
        super().__init__()
        self.signal_data = signal_data
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(signal_data.get('enabled', True))
        
        type_str = "Note" if signal_data.get('type') == 'note' else "CC"
        lbl_text = f"{signal_data.get('name', '')} ({type_str} {signal_data.get('value', 0)} / CH {signal_data.get('channel', 0)+1})"
        self.name_lbl = QLabel(lbl_text)
        
        self.edit_btn = QPushButton("✏️ 編輯")
        self.edit_btn.setFixedSize(70, 30)
        self.delete_btn = QPushButton("🗑️ 刪除")
        self.delete_btn.setFixedSize(70, 30)
        colors = get_theme_colors()
        self.delete_btn.setStyleSheet(f"background-color: {colors.error_bg}; color: white; border: none;")
        
        layout.addWidget(self.checkbox)
        layout.addWidget(self.name_lbl, stretch=1)
        layout.addWidget(self.edit_btn)
        layout.addWidget(self.delete_btn)

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


VERSION = "1.0.3"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"按鍵發話 (PTT) 控制器 v{VERSION}")
        self.resize(450, 550)

        self.config = ConfigManager()
        self.audio_manager = AudioManager()
        self.overlay = MicOffOverlay(self.config)
        self.ptt_worker = PTTWorker(self.audio_manager)
        self.ptt_worker.state_changed.connect(self.on_ptt_state_changed)
        
        self.hotkey = self.config.get('hotkey')
        self.app_widgets = []
        self.listener_thread = None
        self.mover_thread = None
        
        self.midi_check_timer = QTimer(self)
        self.midi_check_timer.timeout.connect(self.check_midi_status_poll)
        self.expected_midi_state = None
        
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
        header_lbl.setFont(get_font(12, bold=True))
        
        self.engine_combo = QComboBox()
        self.engine_combo.setFont(get_font(10))
        self.engine_combo.addItems([
            "Windows 系統麥克風 (目前模式)",
            "Voicemeeter 路由控制",
            "Studio One (MIDI 模式)"
        ])
        saved_engine = self.config.get('engine_type') or 'windows'
        if saved_engine == 'voicemeeter':
            self.engine_combo.setCurrentIndex(1)
        elif saved_engine == 'studioone':
            self.engine_combo.setCurrentIndex(2)
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
        
        # MIDI Controls (hidden by default, shown for Studio One)
        self.midi_frame = QWidget()
        midi_layout = QVBoxLayout(self.midi_frame)
        midi_layout.setAlignment(Qt.AlignCenter)
        
        self.midi_status_lbl = QLabel()
        self.midi_status_lbl.setFont(get_font(12, bold=True))
        self.midi_status_lbl.setAlignment(Qt.AlignCenter)
        
        self.midi_action_btn = QPushButton()
        self.midi_action_btn.setFont(get_font(10, bold=True))
        self.midi_action_btn.setFixedSize(250, 40)
        self.midi_action_btn.clicked.connect(self.handle_midi_action)
        
        self.midi_add_btn = QPushButton("➕ 新增 MIDI 訊號")
        self.midi_add_btn.clicked.connect(self.add_midi_signal)
        
        midi_layout.addWidget(self.midi_status_lbl)
        midi_layout.addWidget(self.midi_action_btn, alignment=Qt.AlignCenter)
        midi_layout.addWidget(self.midi_add_btn, alignment=Qt.AlignCenter)
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
        elif index == 2:
            engine_type = 'studioone'
        else:
            engine_type = 'windows'
            
        self.config.set('engine_type', engine_type)
        self.audio_manager.set_engine(engine_type)
        self.refresh_apps()

    def refresh_apps(self):
        # Clear old
        for w in self.app_widgets:
            self.scroll_layout.removeWidget(w)
            w.deleteLater()
        self.app_widgets.clear()

        struct = self.audio_manager.get_structure()
        
        if struct['type'] == 'midi':
            self.matrix_frame.hide()
            self.refresh_btn.hide()
            self.scroll_area.show()
            self.midi_frame.show()
            
            colors = get_theme_colors()
            
            self.midi_status = struct.get('status', 'not_installed')
            
            if self.midi_status == 'ready':
                self.midi_status_lbl.setText("✅ loopMIDI 驅動已就緒")
                self.midi_status_lbl.setStyleSheet(f"color: {colors.success};")
                self.midi_action_btn.setText("🗑️ 解除安裝 loopMIDI")
                self.midi_action_btn.setStyleSheet(f"background-color: {colors.error_bg}; color: white; border: none;")
                self.midi_add_btn.show()
            elif self.midi_status == 'no_port':
                self.midi_status_lbl.setText("⚠️ 已經安裝 loopMIDI！\n請點擊下方按鈕開啟它，並按左下角的 [+] 新增虛擬線")
                self.midi_status_lbl.setStyleSheet(f"color: #FFA500;") # Orange
                self.midi_action_btn.setText("🚀 第一步：開啟 loopMIDI 介面")
                self.midi_action_btn.setStyleSheet(f"background-color: #0078D4; color: white; border: none;")
                self.midi_add_btn.hide()
            else:
                self.midi_status_lbl.setText("❌ 尚未安裝 loopMIDI 驅動")
                self.midi_status_lbl.setStyleSheet(f"color: {colors.error};")
                self.midi_action_btn.setText("📥 一鍵安裝 loopMIDI")
                self.midi_action_btn.setStyleSheet(f"background-color: #0078D4; color: white; border: none;")
                self.midi_add_btn.hide()
                
            # Render midi signals
            saved_signals = self.config.get('midi_signals', [])
            if not saved_signals and self.midi_status == 'ready':
                lbl = QLabel("請點選上方的「新增 MIDI 訊號」按鈕")
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
            self.matrix_frame.show()
            self.refresh_btn.hide()
            self.midi_frame.hide()
            self.scroll_area.show()
            
            # Update comboboxes
            self.matrix_in_combo.clear()
            self.matrix_out_combo.clear()
            
            self.matrix_in_data = struct['inputs']
            self.matrix_out_data = struct['outputs']
            
            for item in self.matrix_in_data:
                self.matrix_in_combo.addItem(item['name'], userData=item['id'])
            for item in self.matrix_out_data:
                self.matrix_out_combo.addItem(item['name'], userData=item['id'])
                
            # Render saved matrix routes
            saved_devices = self.config.get('selected_apps') or []
            if not saved_devices:
                lbl = QLabel("請在上方選擇輸入與輸出端口，並點擊新增。")
                lbl.setAlignment(Qt.AlignCenter)
                self.scroll_layout.addWidget(lbl)
                self.app_widgets.append(lbl)
            else:
                for route_id in saved_devices:
                    # try to parse name
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
                        
                        # Use default argument capture for lambda in loop
                        w.delete_btn.clicked.connect(lambda checked=False, rid=route_id: self.delete_matrix_route(rid))
                        self.scroll_layout.addWidget(w)
                        self.app_widgets.append(w)
                        
        else:
            self.matrix_frame.hide()
            self.midi_frame.hide()
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

    def check_midi_status_poll(self):
        if self.config.get('engine_type') != 'studioone':
            self.midi_check_timer.stop()
            return
            
        struct = self.audio_manager.get_structure()
        current_status = struct.get('status', 'not_installed')
        
        # If we were expecting a change and it happened
        if self.expected_midi_state is not None and current_status == self.expected_midi_state:
            self.midi_check_timer.stop()
            self.refresh_apps()
            if current_status == 'ready':
                QMessageBox.information(self, "成功", "偵測到 loopMIDI 虛擬線已成功連接！\n現在可以開始綁定訊號了。")
            elif current_status == 'no_port':
                QMessageBox.information(self, "提示", "loopMIDI 驅動已經就緒！\n\n接下來請在彈出的 loopMIDI 視窗中：\n1. 點擊左下角的 [+] 號\n2. 看到清單出現 loopMIDI Port 即可！")
                self.expected_midi_state = 'ready' # Wait for port
                self.midi_check_timer.start(1000)
            else:
                QMessageBox.information(self, "成功", "loopMIDI 已成功解除安裝。")
            self.expected_midi_state = None
        # Also auto-update UI if status changes unexpectedly during polling
        elif current_status == 'ready' and self.expected_midi_state == 'ready':
            self.midi_check_timer.stop()
            self.refresh_apps()
            self.expected_midi_state = None

    def handle_midi_action(self):
        import os
        import subprocess
        
        if self.midi_status == 'not_installed':
            # Install mode
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            installer_path = os.path.join(project_root, 'resources', 'loopMIDISetup.exe')
            if os.path.exists(installer_path):
                os.startfile(installer_path)
                self.expected_midi_state = 'no_port' # First expect it to be installed
                self.midi_check_timer.start(1000)
            else:
                QMessageBox.warning(self, "錯誤", f"找不到安裝檔，尋找路徑為: {installer_path}")
        elif self.midi_status == 'no_port':
            loopmidi_path = r"C:\Program Files (x86)\Tobias Erichsen\loopMIDI\loopMIDI.exe"
            if os.path.exists(loopmidi_path):
                subprocess.Popen(loopmidi_path, shell=True)
                self.expected_midi_state = 'ready'
                self.midi_check_timer.start(1000)
        else:
            # Uninstall mode (open appwiz.cpl)
            QMessageBox.information(self, "提示", "請在即將開啟的視窗中找到「loopMIDI」，點擊解除安裝。\n程式會在背景自動偵測解除安裝進度。")
            subprocess.Popen("appwiz.cpl", shell=True)
            self.expected_midi_state = 'not_installed'
            self.midi_check_timer.start(1000)

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
        reply = QMessageBox.question(self, "刪除", f"確定要刪除 {sig.get('name')} 嗎？", QMessageBox.Yes | QMessageBox.No)
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
        self.refresh_btn.setEnabled(enabled)
        self.set_hotkey_btn.setEnabled(enabled)
        self.mode_ptt_radio.setEnabled(enabled)
        self.mode_toggle_radio.setEnabled(enabled)
        for w in self.app_widgets:
            if isinstance(w, AppItemWidget):
                w.checkbox.setEnabled(enabled)
                
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
