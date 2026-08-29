import os
import warnings
import datetime
import struct
import socket

warnings.filterwarnings("ignore", category=UserWarning, module='pycaw')

def log_debug(msg):
    print(f"[DEBUG] {msg}")

def encode_osc_message(address: str, *args) -> bytes:
    """Encodes an OSC address and arguments into standard OSC 1.0 binary format."""
    def pad4(b: bytes) -> bytes:
        pad_len = (4 - (len(b) % 4)) % 4
        return b + b'\x00' * (pad_len if pad_len else 0)
    
    addr_bytes = address.encode('utf-8') + b'\x00'
    packed = pad4(addr_bytes)
    
    tags = ','
    arg_bytes = b''
    for a in args:
        if isinstance(a, bool):
            tags += 'T' if a else 'F'
        elif isinstance(a, int):
            tags += 'i'
            arg_bytes += struct.pack('>i', a)
        elif isinstance(a, float):
            tags += 'f'
            arg_bytes += struct.pack('>f', a)
        elif isinstance(a, str):
            tags += 's'
            arg_bytes += pad4(a.encode('utf-8') + b'\x00')
    
    tag_bytes = tags.encode('utf-8') + b'\x00'
    packed += pad4(tag_bytes) + arg_bytes
    return packed

def decode_osc_message(data: bytes):
    """Decodes standard OSC 1.0 binary message to (address, args)."""
    parts = data.split(b'\x00', 1)
    addr = parts[0].decode('utf-8', errors='ignore')
    idx = (len(parts[0]) + 4) & ~3
    if idx >= len(data):
        return addr, []
    tag_data = data[idx:].split(b'\x00', 1)[0]
    tags = tag_data.decode('utf-8', errors='ignore')
    idx += (len(tag_data) + 4) & ~3
    args = []
    for t in tags[1:]:
        if t == 'f' and idx + 4 <= len(data):
            val = struct.unpack('>f', data[idx:idx+4])[0]
            args.append(val)
            idx += 4
        elif t == 'i' and idx + 4 <= len(data):
            val = struct.unpack('>i', data[idx:idx+4])[0]
            args.append(val)
            idx += 4
        elif t == 's':
            s_bytes = data[idx:].split(b'\x00', 1)[0]
            args.append(s_bytes.decode('utf-8', errors='ignore'))
            idx += (len(s_bytes) + 4) & ~3
        elif t == 'T':
            args.append(True)
        elif t == 'F':
            args.append(False)
    return addr, args

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
        except Exception as e:
            log_debug(f"Voicemeeter import or connect failed: {e}")
            return False

    def get_structure(self):
        try:
            import voicemeeterlib
        except ImportError:
            return {
                'type': 'matrix',
                'status': 'missing_package',
                'package_name': 'voicemeeter-api',
                'inputs': [],
                'outputs': []
            }
        except Exception as ex:
            return {
                'type': 'matrix',
                'status': 'missing_package',
                'error': str(ex),
                'inputs': [],
                'outputs': []
            }
            
        if not self._connect():
            return {
                'type': 'matrix',
                'status': 'app_not_running',
                'inputs': [],
                'outputs': []
            }
            
        inputs = []
        outputs = []
        try:
            # Inputs
            for i, strip in enumerate(self.v.strip):
                strip_name = strip.label if getattr(strip, 'label', '') else ""
                
                if hasattr(strip, 'device'):
                    # Hardware Strip
                    dev_name = getattr(strip.device, 'name', '')
                    if not dev_name:
                        continue # Skip unconnected physical ports
                    name_str = f"Hardware Input {i+1} ({dev_name})" if not strip_name else f"{strip_name} ({dev_name})"
                else:
                    # Virtual Strip
                    if not strip_name:
                        if "potato" in str(self.kind).lower():
                            names = ["VAIO", "AUX", "VAIO3"]
                            name_str = f"Virtual Input {names[i-5] if i >= 5 and i-5 < len(names) else i}"
                        else:
                            name_str = f"Virtual Input {i}"
                    else:
                        name_str = strip_name
                        
                inputs.append({'id': str(i), 'name': name_str})

            # Outputs (Buses)
            for i, bus in enumerate(self.v.bus):
                bus_name = bus.label if getattr(bus, 'label', '') else ""
                
                # Derive logical names like A1, B1 based on is_physical
                is_physical = hasattr(bus, 'device')
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


class StudioOneOSCEngine(BaseAudioEngine):
    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        self.ip = "127.0.0.1"
        self.port = 8000
        self._sock = None
        self._reload_config()

    def _reload_config(self):
        if self.config_manager:
            self.ip = self.config_manager.get('osc_ip') or "127.0.0.1"
            self.port = int(self.config_manager.get('osc_port') or 8000)
        else:
            self.ip = "127.0.0.1"
            self.port = 8000

    def get_socket(self):
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return self._sock

    def get_structure(self):
        self._reload_config()
        return {
            'type': 'osc',
            'status': 'ready',
            'ip': self.ip,
            'port': self.port
        }

    def send_osc(self, address: str, *args):
        self._reload_config()
        try:
            sock = self.get_socket()
            packet = encode_osc_message(address, *args)
            sock.sendto(packet, (self.ip, self.port))
            log_debug(f"OSC Sent: {address} {args} -> {self.ip}:{self.port}")
            return True, f"已發送 OSC 訊號: {address} {args}"
        except Exception as e:
            log_debug(f"OSC Send Error: {e}")
            return False, f"OSC 發送失敗: {e}"

    def set_mute(self, target_ids, mute: bool):
        # target_ids can be a list of dicts or str addresses
        for sig in target_ids:
            if isinstance(sig, dict):
                address = sig.get('address', '/track/1/mute')
                val_type = sig.get('type', 'float')
                if val_type == 'float':
                    val = float(sig.get('mute_val', 1.0) if mute else sig.get('unmute_val', 0.0))
                elif val_type == 'int':
                    val = int(sig.get('mute_val', 1) if mute else sig.get('unmute_val', 0))
                else:
                    val = bool(mute)
                self.send_osc(address, val)
            elif isinstance(sig, str):
                val = 1.0 if mute else 0.0
                self.send_osc(sig, val)

    def send_test_signal(self):
        self._reload_config()
        s1, d1 = self.send_osc('/track/1/mute', 1.0)
        import time
        time.sleep(0.05)
        s2, d2 = self.send_osc('/track/1/mute', 0.0)
        return (s1 and s2), f"OSC 脈衝 (發送至「{self.ip}:{self.port}」/track/1/mute)"

    def cleanup(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


class AudioManager:
    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        self.engine_type = 'windows'
        osc_engine = StudioOneOSCEngine(config_manager)
        self.engines = {
            'windows': WindowsAudioEngine(),
            'voicemeeter': VoicemeeterEngine(),
            'studioone': osc_engine,
            'studioone_osc': osc_engine
        }

    def set_engine(self, engine_type):
        self.engine_type = engine_type

    def get_current_engine(self):
        return self.engines.get(self.engine_type, self.engines['windows'])

    def get_structure(self):
        return self.get_current_engine().get_structure()

    def set_mute_for_devices(self, target_ids, mute: bool):
        self.get_current_engine().set_mute(target_ids, mute)

    def send_test_signal(self):
        engine = self.get_current_engine()
        if hasattr(engine, 'send_test_signal'):
            return engine.send_test_signal()
        return False, "目前引擎不支援訊號測試"

    def cleanup(self):
        for engine in self.engines.values():
            engine.cleanup()
