import win32api
import os
import warnings
import datetime
from pycaw.pycaw import AudioUtilities
from pycaw.constants import EDataFlow

warnings.filterwarnings("ignore", category=UserWarning, module='pycaw')

def log_debug(msg):
    try:
        log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "ptt_debug.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

class AudioManager:
    def __init__(self):
        pass

    def get_capture_devices(self):
        devices_info = []
        try:
            devices = AudioUtilities.GetAllDevices(EDataFlow.eCapture.value)
            for dev in devices:
                try:
                    if getattr(dev, 'state', 0) != 1: continue
                    vol = dev.EndpointVolume
                    if vol:
                        devices_info.append({
                            'id': dev.id,
                            'name': dev.FriendlyName
                        })
                except Exception:
                    continue
        except Exception as e:
            log_debug(f"Error fetching devices: {e}")
        return devices_info

    def set_mute_for_devices(self, target_ids, mute: bool):
        try:
            devices = AudioUtilities.GetAllDevices(EDataFlow.eCapture.value)
            for dev in devices:
                if getattr(dev, 'state', 0) != 1: continue
                if dev.id in target_ids:
                    try:
                        vol = dev.EndpointVolume
                        if vol:
                            vol.SetMute(1 if mute else 0, None)
                            log_debug(f"成功對 {dev.FriendlyName} 執行了 SetMute({mute})。")
                    except Exception as e:
                        log_debug(f"對 {dev.FriendlyName} 執行 SetMute 失敗: {e}")
        except Exception as e:
            log_debug(f"Error setting mute: {e}")
