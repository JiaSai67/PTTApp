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
        self._connect()

    def _connect(self):
        if self.connected:
            return True
        try:
            import voicemeeterlib
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

    def get_structure(self):
        if not self._connect():
            return {'type': 'matrix', 'inputs': [], 'outputs': []}
            
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
                        if "potato" in str(self.v).lower():
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
                # But actually, potato has A1-A5, B1-B3.
                # A simple mapping for Potato:
                # 0-4: A1-A5, 5-7: B1-B3
                if i < 5:
                    logical = f"A{i+1}"
                else:
                    logical = f"B{i-4}"
                    
                name_str = f"{logical}" + (f" ({bus_name})" if bus_name else "")
                outputs.append({'id': logical, 'name': name_str})

        except Exception as e:
            log_debug(f"Voicemeeter get_structure error: {e}")
            
        return {'type': 'matrix', 'inputs': inputs, 'outputs': outputs}

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
            except Exception:
                pass


class StudioOneEngine(BaseAudioEngine):
    def __init__(self):
        self.outport = None
        self._init_port()

    def _init_port(self):
        if self.outport is not None:
            return True
        try:
            import mido
            ports = mido.get_output_names()
            for p in ports:
                if 'loopMIDI' in p:
                    self.outport = mido.open_output(p)
                    return True
        except ImportError:
            # Auto install dependencies if missing
            import subprocess
            import sys
            subprocess.call([sys.executable, "-m", "pip", "install", "mido", "python-rtmidi"])
            try:
                import mido
                ports = mido.get_output_names()
                for p in ports:
                    if 'loopMIDI' in p:
                        self.outport = mido.open_output(p)
                        return True
            except:
                pass
        except Exception as e:
            pass
        return False

    def get_structure(self):
        # We can re-check the port to see if it's available
        if self._init_port():
            return {'type': 'midi', 'status': 'ready'}
            
        import os
        loopmidi_path = r"C:\Program Files (x86)\Tobias Erichsen\loopMIDI\loopMIDI.exe"
        if os.path.exists(loopmidi_path):
            return {'type': 'midi', 'status': 'no_port'}
            
        return {'type': 'midi', 'status': 'not_installed'}

    def set_mute(self, target_ids, mute: bool):
        if not self._init_port():
            return
            
        try:
            import mido
            for sig in target_ids:
                if not isinstance(sig, dict):
                    continue
                
                channel = sig.get('channel', 0)
                val = sig.get('value', 14)
                if sig.get('type') == 'note':
                    note_type = 'note_on' if mute else 'note_off'
                    vel = 127 if mute else 0
                    msg = mido.Message(note_type, channel=channel, note=val, velocity=vel)
                else:
                    v = 127 if mute else 0
                    msg = mido.Message('control_change', channel=channel, control=val, value=v)
                self.outport.send(msg)
            
        except Exception as e:
            pass

    def cleanup(self):
        if self.outport:
            try:
                self.outport.close()
            except:
                pass
            self.outport = None


class AudioManager:
    def __init__(self):
        self.engine_type = 'windows'
        self.engines = {
            'windows': WindowsAudioEngine(),
            'voicemeeter': VoicemeeterEngine(),
            'studioone': StudioOneEngine()
        }

    def set_engine(self, engine_type):
        self.engine_type = engine_type

    def get_current_engine(self):
        return self.engines.get(self.engine_type, self.engines['windows'])

    def get_structure(self):
        return self.get_current_engine().get_structure()

    def set_mute_for_devices(self, target_ids, mute: bool):
        self.get_current_engine().set_mute(target_ids, mute)
        
    def cleanup(self):
        for engine in self.engines.values():
            engine.cleanup()
