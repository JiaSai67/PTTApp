import win32api
import os
import warnings
from pycaw.pycaw import AudioUtilities
from pycaw.api.audiopolicy import IAudioSessionControl2
from pycaw.utils import AudioSession
from pycaw.constants import EDataFlow

# Suppress COMError warnings from pycaw property fetches
warnings.filterwarnings("ignore", category=UserWarning, module='pycaw')

class AudioManager:
    def __init__(self):
        pass

    def get_file_description(self, exe_path):
        try:
            lang, codepage = win32api.GetFileVersionInfo(exe_path, '\\VarFileInfo\\Translation')[0]
            string_file_info = f'\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileDescription'
            return win32api.GetFileVersionInfo(exe_path, string_file_info)
        except Exception:
            return os.path.basename(exe_path)

    def get_capture_apps(self):
        """Returns a list of dicts: {'name': str, 'exe_path': str, 'exe_name': str}"""
        apps = {}
        ignore_exes = {'svchost.exe', 'audiodg.exe', 'system', 'idle', 'csrss.exe', 'explorer.exe', 'lsass.exe', 'smss.exe'}
        try:
            # Iterate through ALL devices (Playback + Capture) to find all audio apps
            devices = AudioUtilities.GetAllDevices(EDataFlow.eAll.value)
            for dev in devices:
                try:
                    mgr = dev.AudioSessionManager
                    if not mgr: continue
                    
                    enumerator = mgr.GetSessionEnumerator()
                    for i in range(enumerator.GetCount()):
                        ctl = enumerator.GetSession(i)
                        if not ctl: continue
                        ctl2 = ctl.QueryInterface(IAudioSessionControl2)
                        if ctl2:
                            session = AudioSession(ctl2)
                            p = session.Process
                            if p:
                                try:
                                    exe_path = p.exe()
                                    exe_name = p.name().lower()
                                except Exception:
                                    continue
                                
                                if exe_name in ignore_exes:
                                    continue
                                    
                                if exe_path not in apps:
                                    desc = self.get_file_description(exe_path)
                                    apps[exe_path] = {
                                        'name': desc,
                                        'exe_path': exe_path,
                                        'exe_name': exe_name
                                    }
                except Exception:
                    continue
        except Exception as e:
            print(f"Error fetching audio apps: {e}")
        return list(apps.values())

    def set_mute_for_apps(self, target_exe_names, mute: bool):
        """Mutes or unmutes the specified list of executable names for ALL capture devices."""
        try:
            # Only affect Capture devices (microphones/inputs)
            devices = AudioUtilities.GetAllDevices(EDataFlow.eCapture.value)
            for dev in devices:
                try:
                    mgr = dev.AudioSessionManager
                    if not mgr: continue
                    
                    enumerator = mgr.GetSessionEnumerator()
                    for i in range(enumerator.GetCount()):
                        ctl = enumerator.GetSession(i)
                        if not ctl: continue
                        ctl2 = ctl.QueryInterface(IAudioSessionControl2)
                        if ctl2:
                            session = AudioSession(ctl2)
                            if session.Process:
                                try:
                                    exe_name = session.Process.name().lower()
                                except Exception:
                                    continue
                                    
                                if exe_name in target_exe_names:
                                    try:
                                        volume = session.SimpleAudioVolume
                                        volume.SetMute(1 if mute else 0, None)
                                    except Exception:
                                        pass
                except Exception:
                    continue
        except Exception as e:
            print(f"Error setting mute: {e}")
