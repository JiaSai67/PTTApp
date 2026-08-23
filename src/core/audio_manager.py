import os
import warnings
import datetime

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
        try:
            import voicemeeterlib
        except (ImportError, Exception):
            return {'type': 'matrix', 'status': 'not_installed', 'inputs': [], 'outputs': []}
            
        if not self._connect():
            return {'type': 'matrix', 'status': 'not_installed', 'inputs': [], 'outputs': []}
            
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
        self.out_handle = None
        self.connected_port_name = ""
        self.last_devices = []
        self._setup_winmm()
        self._init_port()

    def _setup_winmm(self):
        import ctypes
        self.winmm = ctypes.windll.winmm
        
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
        self.MIDIOUTCAPSW = MIDIOUTCAPSW

        class MIDIOUTCAPSA(ctypes.Structure):
            _fields_ = [
                ("wMid", ctypes.c_ushort),
                ("wPid", ctypes.c_ushort),
                ("vDriverVersion", ctypes.c_uint),
                ("szPname", ctypes.c_char * 32),
                ("wTechnology", ctypes.c_ushort),
                ("wVoices", ctypes.c_ushort),
                ("wNotes", ctypes.c_ushort),
                ("wChannelMask", ctypes.c_ushort),
                ("dwSupport", ctypes.c_uint),
            ]
        self.MIDIOUTCAPSA = MIDIOUTCAPSA

        try:
            self.winmm.midiOutGetNumDevs.restype = ctypes.c_uint
            self.winmm.midiOutGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(MIDIOUTCAPSW), ctypes.c_uint]
            self.winmm.midiOutGetDevCapsW.restype = ctypes.c_uint
            self.winmm.midiOutGetDevCapsA.argtypes = [ctypes.c_size_t, ctypes.POINTER(MIDIOUTCAPSA), ctypes.c_uint]
            self.winmm.midiOutGetDevCapsA.restype = ctypes.c_uint
            self.winmm.midiOutOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint]
            self.winmm.midiOutOpen.restype = ctypes.c_uint
            self.winmm.midiOutShortMsg.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            self.winmm.midiOutShortMsg.restype = ctypes.c_uint
            self.winmm.midiOutClose.argtypes = [ctypes.c_void_p]
            self.winmm.midiOutClose.restype = ctypes.c_uint
        except Exception as e:
            log_debug(f"winmm setup error: {e}")

    def enumerate_devices(self):
        """Enumerate all available MIDI Out devices with Unicode & ANSI fallback"""
        devices = []
        import ctypes
        try:
            num_devs = self.winmm.midiOutGetNumDevs()
            for i in range(num_devs):
                name = ""
                # Try Unicode first
                capsW = self.MIDIOUTCAPSW()
                resW = self.winmm.midiOutGetDevCapsW(i, ctypes.byref(capsW), ctypes.sizeof(capsW))
                if resW == 0 and capsW.szPname:
                    name = capsW.szPname.strip()
                else:
                    # Fallback to ANSI
                    capsA = self.MIDIOUTCAPSA()
                    resA = self.winmm.midiOutGetDevCapsA(i, ctypes.byref(capsA), ctypes.sizeof(capsA))
                    if resA == 0 and capsA.szPname:
                        name = capsA.szPname.decode('mbcs', errors='ignore').strip()

                if name:
                    devices.append({'id': i, 'name': name})
        except Exception as e:
            log_debug(f"enumerate_devices error: {e}")
        self.last_devices = devices
        return devices

    def _init_port(self):
        if self.out_handle is not None:
            return 'ready'

        import ctypes
        devices = self.enumerate_devices()
        if not devices:
            return 'error'

        # Filter out built-in synth devices that cannot be virtual loopback cables
        ignore_keywords = ['wavetable', 'synth', 'mapper', 'synthesizer', 'microsoft gs']
        candidates = []
        for dev in devices:
            dname = dev['name'].lower()
            if not any(k in dname for k in ignore_keywords):
                candidates.append(dev)

        if not candidates:
            return 'no_port'

        # Prioritize 'loopmidi' -> 'loop' -> 'virtual' -> any other candidate
        def match_score(dev):
            dn = dev['name'].lower()
            if 'loopmidi' in dn: return 3
            if 'loop' in dn: return 2
            if 'virtual' in dn or 'cable' in dn: return 1
            return 0

        candidates.sort(key=match_score, reverse=True)
        best_dev = candidates[0]

        hMidiOut = ctypes.c_void_p()
        res = self.winmm.midiOutOpen(ctypes.byref(hMidiOut), best_dev['id'], 0, 0, 0)
        if res == 0:
            self.out_handle = hMidiOut
            self.connected_port_name = best_dev['name']
            log_debug(f"Successfully opened MIDI port: {best_dev['name']} (ID: {best_dev['id']})")
            return 'ready'
        elif res == 4: # MMSYSERR_ALLOCATED
            log_debug(f"MIDI Port {best_dev['name']} is locked (MMSYSERR_ALLOCATED)")
            return 'locked'
        else:
            log_debug(f"midiOutOpen failed on {best_dev['name']} with error code: {res}")
            return 'error'

    def is_admin(self):
        import ctypes
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def is_loopmidi_running(self):
        import subprocess
        try:
            cmd = 'tasklist /FI "IMAGENAME eq loopMIDI.exe" /NH'
            out = subprocess.check_output(cmd, shell=True, text=True, errors='ignore')
            return "loopMIDI.exe" in out
        except Exception:
            return False

    def get_structure(self):
        status = self._init_port()
        devices = self.enumerate_devices()
        dev_names = [d['name'] for d in devices]
        is_adm = self.is_admin()
        lm_running = self.is_loopmidi_running()

        if status == 'ready':
            return {
                'type': 'midi',
                'status': 'ready',
                'port_name': self.connected_port_name,
                'devices': dev_names,
                'is_admin': is_adm,
                'loopmidi_running': lm_running
            }
        elif status == 'locked':
            return {
                'type': 'midi',
                'status': 'locked',
                'devices': dev_names,
                'is_admin': is_adm,
                'loopmidi_running': lm_running
            }

        import os
        loopmidi_path = r"C:\Program Files (x86)\Tobias Erichsen\loopMIDI\loopMIDI.exe"
        if os.path.exists(loopmidi_path):
            return {
                'type': 'midi',
                'status': 'no_port',
                'devices': dev_names,
                'is_admin': is_adm,
                'loopmidi_running': lm_running
            }

        return {
            'type': 'midi',
            'status': 'not_installed',
            'devices': dev_names,
            'is_admin': is_adm,
            'loopmidi_running': lm_running
        }

    def send_midi_message(self, sig, mute: bool):
        if self._init_port() != 'ready':
            return False, "MIDI 埠尚未就緒"

        channel = sig.get('channel', 0)
        val = sig.get('value', 14)
        
        if sig.get('type') == 'note':
            status = 0x90 + channel if mute else 0x80 + channel
            vel = 127 if mute else 0
            msg = status | (val << 8) | (vel << 16)
            desc = f"Note {'ON' if mute else 'OFF'} (Ch:{channel}, Note:{val}, Vel:{vel})"
        else:
            status = 0xB0 + channel
            v = 127 if mute else 0
            msg = status | (val << 8) | (v << 16)
            desc = f"CC (Ch:{channel}, CC:{val}, Val:{v})"
            
        res = self.winmm.midiOutShortMsg(self.out_handle, msg)
        if res != 0:
            log_debug(f"midiOutShortMsg failed with code {res}, attempting auto-reconnect...")
            self.cleanup()
            if self._init_port() == 'ready':
                res = self.winmm.midiOutShortMsg(self.out_handle, msg)

        log_debug(f"MIDI Send: {desc} -> ReturnCode: {res}")
        return (res == 0), desc

    def set_mute(self, target_ids, mute: bool):
        for sig in target_ids:
            if isinstance(sig, dict):
                self.send_midi_message(sig, mute)

    def send_test_signal(self):
        # Send both CC and Note On so whether Studio One created a Control Surface or Keyboard, it captures!
        sig_cc = {'type': 'cc', 'channel': 0, 'value': 14}
        sig_note = {'type': 'note', 'channel': 0, 'value': 60}
        
        s1, d1 = self.send_midi_message(sig_cc, True)
        s2, d2 = self.send_midi_message(sig_note, True)
        
        import time
        time.sleep(0.05)
        self.send_midi_message(sig_cc, False)
        self.send_midi_message(sig_note, False)
        
        return (s1 or s2), f"CC:14 及 Note:60 (C4) 至「{self.connected_port_name}」"

    def generate_midi_diagnostic(self):
        log = []
        log.append("==================================================")
        log.append("       PTTApp 深度系統與 MIDI 環境診斷報告         ")
        log.append("==================================================")
        import sys
        import platform
        import struct
        import datetime
        import subprocess
        import os
        import ctypes
        import winreg

        is_admin = False
        try:
            is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            pass

        log.append(f"診斷時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log.append(f"作業系統: Windows {platform.release()} (組建編號: {platform.version()}) - {platform.machine()}")
        log.append(f"管理員權限 (IsAdmin): {'[YES] 是 (以管理員身分執行)' if is_admin else '[NO] 否 (一般使用者權限)'}")
        log.append(f"Python 版本: {sys.version}")
        log.append(f"Python 位元: {struct.calcsize('P') * 8}-bit")
        log.append(f"執行路徑: {sys.executable}")
        log.append("")

        # [1] loopMIDI Process & Service State
        log.append("--- [1] loopMIDI 與行程執行狀態 ---")
        try:
            cmd = 'tasklist /V /FI "IMAGENAME eq loopMIDI.exe" /FO CSV /NH'
            out = subprocess.check_output(cmd, shell=True, text=True, errors='ignore').strip()
            if "loopMIDI.exe" in out:
                log.append(f"[OK] loopMIDI.exe 正在執行: {out}")
            else:
                log.append("[WARN] loopMIDI.exe 目前未在執行中！請開啟 loopMIDI。")
        except Exception as e:
            log.append(f"檢查行程失敗: {e}")

        loopmidi_path = r"C:\Program Files (x86)\Tobias Erichsen\loopMIDI\loopMIDI.exe"
        log.append(f"loopMIDI.exe 安裝路徑 ({loopmidi_path}): {'[OK] 已存在' if os.path.exists(loopmidi_path) else '[ERROR] 不存在'}")
        log.append("")

        # [2] Driver Files on Disk
        log.append("--- [2] 系統底層虛擬驅動檔案完整性檢查 ---")
        driver_files = [
            r"C:\Windows\System32\drivers\teVirtualMIDI64.sys",
            r"C:\Windows\System32\drivers\teVirtualMIDI.sys",
            r"C:\Windows\System32\teVirtualMIDI64.dll",
            r"C:\Windows\SysWOW64\teVirtualMIDI32.dll",
            r"C:\Windows\System32\loopMIDIdrv64.dll",
            r"C:\Windows\SysWOW64\loopMIDIdrv.dll",
            r"C:\Program Files (x86)\Tobias Erichsen\loopMIDI\teVirtualMIDI64.dll",
            r"C:\Program Files (x86)\Tobias Erichsen\loopMIDI\teVirtualMIDI32.dll"
        ]
        for df in driver_files:
            log.append(f"  - {df}: {'[OK] 存在' if os.path.exists(df) else '[MISSING] 不存在'}")
        log.append("")

        # [3] Registry Drivers32 Registration
        log.append("--- [3] Windows 登錄檔 Drivers32 MIDI 驅動註冊檢查 ---")
        for view_name, flags in [("64-bit View", winreg.KEY_WOW64_64KEY), ("32-bit View", winreg.KEY_WOW64_32KEY)]:
            log.append(f"  * 登錄檔位置: HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Drivers32 ({view_name})")
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Drivers32", 0, winreg.KEY_READ | flags) as key:
                    i = 0
                    found_any = False
                    while True:
                        try:
                            val_name, val_data, _ = winreg.EnumValue(key, i)
                            if val_name.lower().startswith("midi"):
                                log.append(f"     -> {val_name} = '{val_data}'")
                                found_any = True
                            i += 1
                        except OSError:
                            break
                    if not found_any:
                        log.append("     [WARN] 找不到任何 midi* 登錄鍵！")
            except Exception as e:
                log.append(f"     [ERROR] 無法讀取登錄檔: {e}")
        log.append("")

        # [4] Windows Audio & MIDI Services
        log.append("--- [4] Windows 核心音訊與 MIDI 服務狀態 ---")
        for srv in ["Audiosrv", "AudioEndpointBuilder", "MidiSrv", "teVirtualMIDI"]:
            try:
                cmd = f'sc query "{srv}"'
                out = subprocess.check_output(cmd, shell=True, text=True, errors='ignore')
                state_line = next((l.strip() for l in out.splitlines() if "STATE" in l), "UNKNOWN")
                log.append(f"  - 服務 {srv}: {state_line}")
            except Exception:
                log.append(f"  - 服務 {srv}: [NOT FOUND 或無此服務]")
        log.append("")

        # [5] PnP Device Manager Status via PowerShell
        log.append("--- [5] Windows 裝置管理員 (PnP) 狀態 ---")
        try:
            ps_cmd = 'powershell -NoProfile -Command "Get-PnpDevice | Where-Object { $_.FriendlyName -like \'*MIDI*\' -or $_.Class -eq \'MEDIA\' -or $_.FriendlyName -like \'*loop*\' } | Select-Object Status, ProblemCode, ConfigManagerErrorCode, FriendlyName, Class | Format-Table -AutoSize | Out-String -Width 4096"'
            pnp_out = subprocess.check_output(ps_cmd, shell=True, text=True, errors='ignore').strip()
            log.append(pnp_out if pnp_out else "[WARN] 未找到任何符合條件的 PnP 裝置。")
        except Exception as e:
            log.append(f"[ERROR] 查詢 PnP 裝置失敗: {e}")
        log.append("")

        # [6] Direct teVirtualMIDI C-API Probe
        log.append("--- [6] 直接呼叫 teVirtualMIDI 核心 DLL API 探測 ---")
        te_dll_candidates = [
            r"C:\Windows\System32\teVirtualMIDI64.dll",
            r"C:\Program Files (x86)\Tobias Erichsen\loopMIDI\teVirtualMIDI64.dll",
            r"C:\Windows\SysWOW64\teVirtualMIDI32.dll",
            r"C:\Program Files (x86)\Tobias Erichsen\loopMIDI\teVirtualMIDI32.dll"
        ]
        loaded_te = False
        for dll_path in te_dll_candidates:
            if os.path.exists(dll_path):
                try:
                    te_lib = ctypes.cdll.LoadLibrary(dll_path)
                    log.append(f"  [OK] 成功載入: {dll_path}")
                    if hasattr(te_lib, 'virtualMIDIGetVersion'):
                        try:
                            te_lib.virtualMIDIGetVersion.restype = ctypes.c_uint
                            te_lib.virtualMIDIGetVersion.argtypes = []
                            ver = te_lib.virtualMIDIGetVersion()
                            log.append(f"     -> 驅動程式版本代碼 (virtualMIDIGetVersion): {ver}")
                            loaded_te = True
                            break
                        except Exception as ex:
                            log.append(f"     -> 呼叫 virtualMIDIGetVersion 發生錯誤: {ex}")
                except Exception as e:
                    log.append(f"  [FAIL] 載入 {dll_path} 失敗: {e}")
        if not loaded_te:
            log.append("  [WARN] 未能成功與 teVirtualMIDI DLL 進行 API 通訊。")
        log.append("")

        # [7] WinMM API Output & Input Device Enumeration
        log.append("--- [7] WinMM 傳統多媒體 API 裝置清單 ---")
        try:
            num_out = self.winmm.midiOutGetNumDevs()
            log.append(f"MIDI 輸出裝置數量 (midiOutGetNumDevs): {num_out}")
            for i in range(num_out):
                capsW = self.MIDIOUTCAPSW()
                resW = self.winmm.midiOutGetDevCapsW(i, ctypes.byref(capsW), ctypes.sizeof(capsW))
                nameW = capsW.szPname if resW == 0 else f"<Unicode 失敗: 代碼 {resW}>"
                
                capsA = self.MIDIOUTCAPSA()
                resA = self.winmm.midiOutGetDevCapsA(i, ctypes.byref(capsA), ctypes.sizeof(capsA))
                nameA = capsA.szPname.decode('mbcs', errors='ignore') if resA == 0 else f"<ANSI 失敗: 代碼 {resA}>"
                
                log.append(f"  [輸出 ID {i}]: Unicode='{nameW}', ANSI='{nameA}'")
                
                # Test opening
                hMidiOut = ctypes.c_void_p()
                open_res = self.winmm.midiOutOpen(ctypes.byref(hMidiOut), i, 0, 0, 0)
                if open_res == 0:
                    log.append(f"     連接測試: [OK] 成功開啟連接埠 (Handle: {hMidiOut.value})")
                    self.winmm.midiOutClose(hMidiOut)
                elif open_res == 4:
                    log.append(f"     連接測試: [WARN] MMSYSERR_ALLOCATED (4) - 埠已被其他程式獨佔")
                else:
                    log.append(f"     連接測試: [ERROR] 開啟失敗，錯誤代碼: {open_res}")
                    
            if hasattr(self.winmm, 'midiInGetNumDevs'):
                num_in = self.winmm.midiInGetNumDevs()
                log.append(f"MIDI 輸入裝置數量 (midiInGetNumDevs): {num_in}")
        except Exception as e:
            import traceback
            log.append(f"WinMM 檢測過程發生錯誤:\n{traceback.format_exc()}")

        log.append("")
        log.append("==================================================")
        log.append("診斷結束。請將以上完整內容複製或截圖回傳。")
        log.append("==================================================")
        
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        log_path = os.path.join(project_root, 'midi_diagnostic.txt')
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(log))
            
        return log_path

    def cleanup(self):
        if self.out_handle:
            try:
                self.winmm.midiOutClose(self.out_handle)
            except Exception:
                pass
            self.out_handle = None


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
        
    def generate_midi_diagnostic(self):
        engine = self.get_current_engine()
        if hasattr(engine, 'generate_midi_diagnostic'):
            return engine.generate_midi_diagnostic()
        return None

    def send_test_signal(self):
        engine = self.get_current_engine()
        if hasattr(engine, 'send_test_signal'):
            return engine.send_test_signal()
        return False, "目前引擎不支援 MIDI 測試"

    def cleanup(self):
        for engine in self.engines.values():
            engine.cleanup()
