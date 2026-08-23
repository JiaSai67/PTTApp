from pynput import keyboard, mouse
from PySide6.QtCore import QObject, Signal

def get_key_name(key):
    if hasattr(key, 'name'):
        return key.name
    elif hasattr(key, 'char'):
        return key.char
    return str(key).strip("'")

class PTTWorker(QObject):
    state_changed = Signal(bool) # True = Unmuted, False = Muted

    def __init__(self, audio_manager):
        super().__init__()
        self.audio_manager = audio_manager
        self.target_exe_names = []
        self.hotkey_parts = set()
        
        self.is_running = False
        self.is_active = False
        self.keys_down = False
        self.current_pressed = set()
        self.mode = 'ptt'
        
        self.k_listener = None
        self.m_listener = None
        
    def start(self, hotkey_str, target_device_ids, mode='ptt'):
        self.hotkey_parts = set(hotkey_str.split('+'))
        self.target_device_ids = target_device_ids
        self.mode = mode
        
        if not self.hotkey_parts or not self.target_device_ids:
            return False
            
        self.is_running = True
        self.is_active = False
        self.keys_down = False
        self.current_pressed.clear()
        
        # Initial state: Mute the target devices
        self.audio_manager.set_mute_for_devices(self.target_device_ids, mute=True)
        self.state_changed.emit(False)
        
        self.k_listener = keyboard.Listener(on_press=self._on_k_press, on_release=self._on_k_release)
        self.m_listener = mouse.Listener(on_click=self._on_m_click)
        self.k_listener.start()
        self.m_listener.start()
        
        return True
        
    def stop(self):
        self.is_running = False
        if self.k_listener:
            self.k_listener.stop()
            self.k_listener = None
        if self.m_listener:
            self.m_listener.stop()
            self.m_listener = None
            
        # Restore state: Unmute the target devices
        self.audio_manager.set_mute_for_devices(self.target_device_ids, mute=False)
        self.state_changed.emit(True) # Treat as unmuted when stopped
        
        self.target_device_ids = []
        self.is_active = False
        self.keys_down = False
        self.current_pressed.clear()

    def _check_state(self):
        if not self.is_running: return
        
        all_pressed = self.hotkey_parts.issubset(self.current_pressed)
        
        if self.mode == 'ptt':
            if all_pressed and not self.is_active:
                self.is_active = True
                self.audio_manager.set_mute_for_devices(self.target_device_ids, mute=False)
                self.state_changed.emit(True)
            elif not all_pressed and self.is_active:
                self.is_active = False
                self.audio_manager.set_mute_for_devices(self.target_device_ids, mute=True)
                self.state_changed.emit(False)
                
        elif self.mode == 'toggle':
            if all_pressed and not self.keys_down:
                self.is_active = not self.is_active
                self.audio_manager.set_mute_for_devices(self.target_device_ids, mute=not self.is_active)
                self.state_changed.emit(self.is_active)
                
        self.keys_down = all_pressed

    def _on_k_press(self, key):
        name = get_key_name(key)
        if name:
            self.current_pressed.add(name)
            self._check_state()

    def _on_k_release(self, key):
        name = get_key_name(key)
        if name in self.current_pressed:
            self.current_pressed.remove(name)
            self._check_state()

    def _on_m_click(self, x, y, button, pressed):
        name = get_key_name(button)
        if name:
            if pressed:
                self.current_pressed.add(name)
            elif name in self.current_pressed:
                self.current_pressed.remove(name)
            self._check_state()
