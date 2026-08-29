import os
import warnings
import datetime
import struct
import socket

warnings.filterwarnings("ignore", category=UserWarning, module='pycaw')

def log_debug(msg):
    print(f"[DEBUG] {msg}")

class BaseAudioEngine:
    def get_structure(self):
        """Returns structure dict for UI rendering"""
        return {'type': 'list', 'items': []}
        
    def set_mute(self, target_ids, mute: bool):
        pass

    def cleanup(self):
        pass


class WindowsAudioEngine(BaseAudioEngine):
    def get_structure(self):
        from pycaw.pycaw import AudioUtilities
        from pycaw.constants import EDataFlow
        devices_info = []
        try:
            devices = AudioUtilities.GetAllDevices(EDataFlow.eCapture.value)
            for dev in devices:
                try:
                    state = getattr(dev, 'state', None)
                    if not state or str(state) != "AudioDeviceState.Active": 
                        continue
                    vol = dev.EndpointVolume
                    if vol:
                        devices_info.append({
                            'id': dev.id,
                            'name': dev.FriendlyName
                        })
                except Exception:
                    continue
        except Exception as e:
            log_debug(f"Error fetching windows devices: {e}")
        return {'type': 'list', 'items': devices_info}

    def set_mute(self, target_ids, mute: bool):
        from pycaw.pycaw import AudioUtilities
        from pycaw.constants import EDataFlow
        try:
            devices = AudioUtilities.GetAllDevices(EDataFlow.eCapture.value)
            for dev in devices:
                state = getattr(dev, 'state', None)
                if not state or str(state) != "AudioDeviceState.Active": 
                    continue
                if dev.id in target_ids:
                    try:
                        vol = dev.EndpointVolume
                        if vol:
                            vol.SetMute(1 if mute else 0, None)
                            log_debug(f"Windows SetMute({mute}) on {dev.FriendlyName}")
                    except Exception as e:
                        log_debug(f"Windows SetMute failed on {dev.FriendlyName}: {e}")
        except Exception as e:
            log_debug(f"Error setting mute: {e}")


class VoicemeeterEngine(BaseAudioEngine):
    def __init__(self):
        self.v = None
        self.connected = False
        self.kind = ""
        self._connect()

    def _connect(self):
        if self.connected and self.v:
            return True
        try:
            import voicemeeterlib
            for kind in ['potato', 'banana', 'basic']:
                try:
                    v = voicemeeterlib.api(kind)
                    v.login()
                    self.v = v
                    self.connected = True
                    self.kind = kind
                    log_debug(f"Voicemeeter {kind} API connected successfully.")
                    return True
                except Exception as ex:
                    log_debug(f"Voicemeeter {kind} connection attempt failed: {ex}")
                    self.v = None
            return False
        except ImportError:
            log_debug("voicemeeter-api package is not installed.")
            return False
        except Exception as e:
            log_debug(f"Voicemeeter general connection error: {e}")
            return False

    def get_structure(self):
        import sys
        try:
            import voicemeeterlib
        except ImportError:
            return {'type': 'matrix', 'status': 'missing_package', 'inputs': [], 'outputs': []}

        if not self._connect():
            return {'type': 'matrix', 'status': 'app_not_running', 'inputs': [], 'outputs': []}

        inputs = []
        outputs = []
        try:
            for i, strip in enumerate(self.v.strip):
                strip_name = strip.label if getattr(strip, 'label', '') else ""
                is_physical = hasattr(strip, 'device')
                
                if strip_name:
                    name_str = f"Strip {i} ({strip_name})"
                else:
                    if not is_physical:
                        if "potato" in str(self.kind).lower():
                            names = ["VAIO", "AUX", "VAIO3"]
                            name_str = f"Virtual Input {names[i-5] if i >= 5 and i-5 < len(names) else i}"
                        else:
                            name_str = f"Virtual Input {i}"
                    else:
                        name_str = f"Hardware Input {i+1}"
                        
                inputs.append({'id': str(i), 'name': name_str})

            for i, bus in enumerate(self.v.bus):
                bus_name = bus.label if getattr(bus, 'label', '') else ""
                if "potato" in str(self.kind).lower():
                    logical = f"A{i+1}" if i < 5 else f"B{i-4}"
                elif "banana" in str(self.kind).lower():
                    logical = f"A{i+1}" if i < 3 else f"B{i-2}"
                else:
                    logical = f"A{i+1}" if i < 2 else f"B{i-1}"
                    
                name_str = f"{logical}" + (f" ({bus_name})" if bus_name else "")
                outputs.append({'id': logical, 'name': name_str})

        except Exception as e:
            log_debug(f"Voicemeeter get_structure error: {e}")
            return {'type': 'matrix', 'status': 'app_not_running', 'inputs': [], 'outputs': []}
            
        return {
            'type': 'matrix',
            'status': 'ready',
            'kind': getattr(self, 'kind', 'voicemeeter'),
            'inputs': inputs,
            'outputs': outputs
        }

    def set_mute(self, target_ids, mute: bool):
        if not self._connect():
            return
            
        try:
            for item_id in target_ids:
                parts = item_id.split('_')
                if len(parts) == 3:
                    strip_idx = int(parts[1])
                    bus_attr = parts[2]
                    
                    if strip_idx < len(self.v.strip):
                        strip = self.v.strip[strip_idx]
                        if hasattr(strip, bus_attr):
                            val = not mute
                            setattr(strip, bus_attr, val)
                            log_debug(f"Voicemeeter set {bus_attr} on Strip {strip_idx} to {val}")
        except Exception as e:
            log_debug(f"Voicemeeter set_mute error: {e}")

    def cleanup(self):
        if self.connected and self.v:
            try:
                self.v.logout()
                self.connected = False
                self.v = None
            except Exception:
                pass


class StudioOneLoopBeEngine(BaseAudioEngine):
    """
    Studio One LoopBe / MIDI 專用虛擬傳輸線引擎
    - 單一 Port (LoopBe Internal MIDI) 支援 2048 個獨立開關
    - 專門控制 Track Mute、CueMix 電腦觀眾、OTG、手機等
    """
    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        self.out_handle = None
        self.connected_port_name = ""
        self._init_port()

    def _get_devices(self):
        import ctypes
        winmm = ctypes.windll.winmm
        class MIDIOUTCAPSW(ctypes.Structure):
            _fields_ = [
                ("wMid", ctypes.c_ushort),
                ("wPid", ctypes.c_ushort),
                ("vDriverVersion", ctypes.c_uint),
                ("szPname", ctypes.c_wchar * 32),
                ("wTechnology", ctypes.c_ushort),
                ("wVoices", ctypes.c_ushort),
                ("wNotes", ctypes.c_ushort),
                ("wChannelMask", ctypes.c_ushort),
                ("dwSupport", ctypes.c_uint),
            ]
        devs = []
        try:
            num = winmm.midiOutGetNumDevs()
            for i in range(num):
                caps = MIDIOUTCAPSW()
                if winmm.midiOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                    name = caps.szPname.strip()
                    if not any(k in name.lower() for k in ['wavetable', 'synth', 'mapper']):
                        devs.append({'id': i, 'name': name})
        except Exception:
            pass
        return devs

    def _init_port(self):
        if self.out_handle is not None:
            return 'ready'

        import ctypes
        winmm = ctypes.windll.winmm
        devs = self._get_devices()
        if not devs:
            return 'no_port'

        def score(d):
            n = d['name'].lower()
            if 'loopbe' in n: return 3
            if 'loopmidi' in n: return 2
            if 'loop' in n or 'virtual' in n: return 1
            return 0

        devs.sort(key=score, reverse=True)
        best = devs[0]
        
        h = ctypes.c_void_p()
        res = winmm.midiOutOpen(ctypes.byref(h), best['id'], 0, 0, 0)
        if res == 0:
            self.out_handle = h
            self.connected_port_name = best['name']
            log_debug(f"Studio One MIDI Port opened: {best['name']}")
            return 'ready'
        return 'error'

    def get_structure(self):
        status = self._init_port()
        if status == 'ready':
            return {
                'type': 'studioone_loopbe',
                'status': 'ready',
                'port_name': self.connected_port_name
            }
        return {
            'type': 'studioone_loopbe',
            'status': 'need_loopbe',
            'port_name': ''
        }

    def send_cc(self, cc_num: int, val: int, channel: int = 0):
        if self._init_port() != 'ready' or not self.out_handle:
            return False
        import ctypes
        winmm = ctypes.windll.winmm
        status_byte = 0xB0 + (channel & 0x0F)
        msg = status_byte | ((cc_num & 0x7F) << 8) | ((val & 0x7F) << 16)
        res = winmm.midiOutShortMsg(self.out_handle, msg)
        if res != 0:
            self.cleanup()
            if self._init_port() == 'ready':
                winmm.midiOutShortMsg(self.out_handle, msg)
        return True

    def set_mute(self, target_ids, mute: bool):
        val = 127 if mute else 0
        for idx, item in enumerate(target_ids):
            if isinstance(item, dict):
                cc = int(item.get('cc_num', 14 + idx))
                ch = int(item.get('channel', 0))
                self.send_cc(cc, val, ch)
                log_debug(f"LoopBe Send -> CC:{cc}, Val:{val}, Ch:{ch} ({item.get('name')})")
            elif isinstance(item, str):
                self.send_cc(14 + idx, val, 0)

    def send_test_signal(self, cc_num: int = 14):
        self._init_port()
        self.send_cc(cc_num, 127)
        import time
        time.sleep(0.06)
        self.send_cc(cc_num, 0)
        return True, f"已向「{self.connected_port_name}」發送 CC:{cc_num} 測試脈衝"

    def cleanup(self):
        if self.out_handle:
            try:
                import ctypes
                ctypes.windll.winmm.midiOutClose(self.out_handle)
            except Exception:
                pass
            self.out_handle = None


class AudioManager:
    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        self.engine_type = 'windows'
        loopbe_engine = StudioOneLoopBeEngine(config_manager)
        self.engines = {
            'windows': WindowsAudioEngine(),
            'voicemeeter': VoicemeeterEngine(),
            'studioone': loopbe_engine,
            'studioone_loopbe': loopbe_engine
        }

    def set_engine(self, engine_type):
        self.engine_type = engine_type

    def get_current_engine(self):
        return self.engines.get(self.engine_type, self.engines['windows'])

    def get_structure(self):
        return self.get_current_engine().get_structure()

    def set_mute_for_devices(self, target_ids, mute: bool):
        self.get_current_engine().set_mute(target_ids, mute)

    def send_test_signal(self, cc_num: int = 14):
        engine = self.get_current_engine()
        if hasattr(engine, 'send_test_signal'):
            return engine.send_test_signal(cc_num)
        return False, "目前引擎不支援訊號測試"

    def cleanup(self):
        for engine in self.engines.values():
            engine.cleanup()
