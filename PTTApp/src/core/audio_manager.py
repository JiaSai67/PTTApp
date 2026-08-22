import os
import warnings
import datetime

warnings.filterwarnings("ignore", category=UserWarning, module='pycaw')

def log_debug(msg):
    try:
        log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "ptt_debug.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

class BaseAudioEngine:
    def get_items(self):
        """Returns a list of dicts with {'id': str, 'name': str}"""
        return []
        
    def set_mute(self, target_ids, mute: bool):
        pass

    def cleanup(self):
        pass


class WindowsAudioEngine(BaseAudioEngine):
    def get_items(self):
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
        return devices_info

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
        self._connect()

    def _connect(self):
        if self.connected:
            return True
        try:
            import voicemeeterlib
            # Try connecting to the running voicemeeter. 
            # kind_id can be 'basic', 'banana', 'potato'. We can try potato first.
            try:
                self.v = voicemeeterlib.api('potato')
                self.v.login()
                self.connected = True
            except Exception:
                try:
                    self.v = voicemeeterlib.api('banana')
                    self.v.login()
                    self.connected = True
                except Exception:
                    self.v = voicemeeterlib.api('basic')
                    self.v.login()
                    self.connected = True
            log_debug("Voicemeeter API connected.")
            return True
        except Exception as e:
            log_debug(f"Voicemeeter connect failed: {e}")
            return False

    def get_items(self):
        if not self._connect():
            return []
            
        items = []
        try:
            # For each strip, we can route to multiple buses.
            # Typical buses in Potato: A1..A5, B1..B3
            # In Banana: A1..A3, B1..B2
            # We list endpoints like: "Strip 0 (Mic) -> Bus B1"
            
            # Map bus index to label (A1, B1 etc.)
            bus_labels = []
            for b in self.v.bus:
                bus_labels.append(b.label if b.label else f"Bus")
                
            for i, strip in enumerate(self.v.strip):
                strip_name = strip.label if strip.label else f"Strip {i}"
                if not strip_name.strip():
                    strip_name = f"Hardware Input {i+1}"
                
                # We can toggle routing to any Bus. Let's list all valid bus toggles for this strip.
                # A strip has attributes A1, A2, B1, B2 etc.
                for attr in ['A1', 'A2', 'A3', 'A4', 'A5', 'B1', 'B2', 'B3']:
                    if hasattr(strip, attr):
                        # Example ID: "strip_0_B1"
                        item_id = f"strip_{i}_{attr}"
                        item_name = f"{strip_name} ➜ {attr}"
                        items.append({'id': item_id, 'name': item_name})
        except Exception as e:
            log_debug(f"Voicemeeter get_items error: {e}")
        return items

    def set_mute(self, target_ids, mute: bool):
        if not self._connect():
            return
            
        try:
            for item_id in target_ids:
                # item_id format: "strip_{index}_{bus}"
                parts = item_id.split('_')
                if len(parts) == 3:
                    strip_idx = int(parts[1])
                    bus_attr = parts[2]
                    
                    if strip_idx < len(self.v.strip):
                        strip = self.v.strip[strip_idx]
                        if hasattr(strip, bus_attr):
                            # If mute is True, we turn OFF the routing (False)
                            # If mute is False, we turn ON the routing (True)
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
            except Exception:
                pass


class AudioManager:
    def __init__(self):
        self.engine_type = 'windows'
        self.engines = {
            'windows': WindowsAudioEngine(),
            'voicemeeter': VoicemeeterEngine()
        }

    def set_engine(self, engine_type):
        self.engine_type = engine_type

    def get_current_engine(self):
        return self.engines.get(self.engine_type, self.engines['windows'])

    def get_capture_devices(self):
        return self.get_current_engine().get_items()

    def set_mute_for_devices(self, target_ids, mute: bool):
        self.get_current_engine().set_mute(target_ids, mute)
        
    def cleanup(self):
        for engine in self.engines.values():
            engine.cleanup()
