import ctypes
import json
import os
import subprocess
import sys
import threading
import time

# Khởi tạo DNS override sớm để tránh DNS block
try:
    from modules.dns_override import install as install_custom_dns
    install_custom_dns()
except Exception:
    pass

from modules.display import (
    close_current_popup,
    show_answers_popup,
    show_notification_popup,
    show_started_popup
)
from modules.hotkey_capmanhinh import ScreenCapturer, load_config
from modules.path_utils import resolve_settings_path
from modules.solver import solve_with_llm

_mid_poll_thread = None
_mid_poll_stop = threading.Event()
_kb_poll_threads = []
_kb_poll_stop = threading.Event()

_user32_poll = ctypes.windll.user32 if os.name == 'nt' else None
_VK_MBUTTON = 0x04

_VK_MAP = {
    'ctrl': 0x11, 'control': 0x11, 'lctrl': 0xA2, 'rctrl': 0xA3,
    'shift': 0x10, 'lshift': 0xA0, 'rshift': 0xA1,
    'alt': 0x12, 'menu': 0x12, 'lalt': 0xA4, 'ralt': 0xA5,
    'x': 0x58, 'z': 0x5A, 'l': 0x4C, 'a': 0x41, 'b': 0x42, 'c': 0x43,
    'd': 0x44, 'e': 0x45, 'f': 0x46, 'g': 0x47, 'h': 0x48, 'i': 0x49,
    'j': 0x4A, 'k': 0x4B, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F, 'p': 0x50,
    'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54, 'u': 0x55, 'v': 0x56,
    'w': 0x57, 'y': 0x59,
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
    '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    'esc': 0x1B, 'escape': 0x1B, 'tab': 0x09, 'space': 0x20,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74, 'f6': 0x75,
    'f7': 0x76, 'f8': 0x77, 'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B
}

_PROXY_URL = "http://103.187.4.82:50053"

def _parse_hotkey_vks(hotkey_str):
    if os.name != 'nt' or not hotkey_str:
        return []
    parts = [p.strip().lower() for p in hotkey_str.split('+')]
    vks = []
    for p in parts:
        if p in _VK_MAP:
            vks.append(_VK_MAP[p])
        elif len(p) == 1:
            vks.append(ord(p.upper()))
    return vks

def _mid_click_poll(callback):
    was_pressed = False
    while not _mid_poll_stop.is_set():
        try:
            if os.name == 'nt' and _user32_poll:
                state = bool(_user32_poll.GetAsyncKeyState(_VK_MBUTTON) & 0x8000)
                if state and not was_pressed:
                    was_pressed = True
                    callback()
                elif not state and was_pressed:
                    was_pressed = False
        except Exception:
            pass
        time.sleep(0.05)

def _install_middle_click_hook(callback):
    global _mid_poll_thread
    _mid_poll_stop.clear()
    _mid_poll_thread = threading.Thread(target=_mid_click_poll, args=(callback,), daemon=True)
    _mid_poll_thread.start()

def _kb_combo_poll(vks, callback):
    was_triggered = False
    while not _kb_poll_stop.is_set():
        try:
            if os.name == 'nt' and _user32_poll:
                all_pressed = all(bool(_user32_poll.GetAsyncKeyState(vk) & 0x8000) for vk in vks)
                if all_pressed and not was_triggered:
                    was_triggered = True
                    callback()
                elif not all_pressed and was_triggered:
                    was_triggered = False
        except Exception:
            pass
        time.sleep(0.05)

def _install_keyboard_poll(hotkey_str, callback):
    vks = _parse_hotkey_vks(hotkey_str)
    if not vks:
        return
    _kb_poll_stop.clear()
    t = threading.Thread(target=_kb_combo_poll, args=(vks, callback), daemon=True)
    t.start()
    _kb_poll_threads.append(t)

def _uninstall_middle_click_hook():
    _mid_poll_stop.set()

def _uninstall_keyboard_poll():
    _kb_poll_stop.set()

def _to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ('1', 'on', 'yes', 'true'):
            return True
        if v in ('0', 'off', 'no', 'false'):
            return False
    return default

def _load_boot_settings():
    settings_path = resolve_settings_path()
    try:
        with open(settings_path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return {}

def _apply_console_visibility(show_console):
    if os.name == 'nt' and not show_console:
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass

class CapSolveApp:
    def __init__(self):
        boot_cfg = _load_boot_settings()
        show_console = _to_bool(boot_cfg.get('app', {}).get('show_console', False), default=False)
        _apply_console_visibility(show_console)

        self.config = load_config()
        self.capturer = ScreenCapturer(config=self.config)
        self.is_processing = False
        self.processing_lock = threading.Lock()
        self.is_shutting_down = False
        self.shutdown_lock = threading.Lock()
        self.use_proxy = False

    def process_and_solve(self):
        if self.is_shutting_down:
            return
        if not self.processing_lock.acquire(blocking=False):
            return

        self.is_processing = True
        try:
            close_current_popup(wait=True)
            self.config = load_config()
            self.capturer = ScreenCapturer(config=self.config)
            start_time = time.time()

            tag = " (qua proxy)" if self.use_proxy else ""
            print("\n==================================================")
            print(f"[*] Đang thực hiện chụp màn hình và giải bài{tag}...")
            show_notification_popup("starting", "#22c55e", self.config)

            image_path = self.capturer.capture_full_screen()
            if not image_path or not os.path.exists(image_path):
                print(f"[-] Không thể chụp ảnh hoặc tìm thấy file ảnh: {image_path}")
                show_notification_popup("Screenshot failed", "#ef4444", self.config)
                return

            proxy_url = _PROXY_URL if self.use_proxy else None
            result = solve_with_llm(image_path, proxy_url=proxy_url)

            elapsed_time = time.time() - start_time
            print("\n[KẾT QUẢ TỪ AI]:")
            if "error" in result:
                print(f"[-] Lỗi: {result['error']}")
                show_notification_popup(f"Error: {result['error']}", "#ef4444", self.config)
            else:
                print(json.dumps(result, indent=4, ensure_ascii=False))
                show_answers_popup(result, self.config)

            print(f"\n[time from snapshot to receive ans] : {elapsed_time:.2f}s")
            print("==================================================\n")
        except Exception as e:
            print(f"[-] Lỗi nghiêm trọng trong luồng xử lý: {e}")
        finally:
            self.is_processing = False
            self.processing_lock.release()

    def on_hotkey_pressed(self):
        if not self.is_shutting_down:
            threading.Thread(target=self.process_and_solve, daemon=True).start()

    def on_hotkey_pressed_proxy(self):
        if not self.is_shutting_down:
            self.use_proxy = not self.use_proxy
            text = "Proxy enabled" if self.use_proxy else "Proxy disabled"
            dot_color = "#22c55e" if self.use_proxy else "#ef4444"
            print(f"[*] {text}")
            show_notification_popup(text, dot_color, self.config)

    def _kill_other_cap_solve_processes(self):
        current_pid = os.getpid()
        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                try:
                    pid = proc.info.get('pid')
                    if pid == current_pid:
                        continue
                    name = str(proc.info.get('name', '')).lower()
                    exe_name = os.path.basename(str(proc.info.get('exe', ''))).lower()
                    if (name.startswith('cap_solve') or exe_name.startswith('cap_solve') or
                        name == 'ok.exe' or exe_name == 'ok.exe'):
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except Exception:
            pass

        # Thêm phương án qua PowerShell nếu Windows
        if os.name == 'nt':
            try:
                cmd = "Get-Process -Name 'cap_solve*', 'ok' -ErrorAction SilentlyContinue | Where-Object {$_.Id -ne " + str(current_pid) + "} | Stop-Process -Force"
                subprocess.run(['powershell', '-NoProfile', '-Command', cmd], capture_output=True, timeout=3)
            except Exception:
                pass

    def _force_shutdown_now(self):
        try:
            close_current_popup(wait=True)
        except Exception:
            pass
        try:
            import keyboard
            keyboard.unhook_all_hotkeys() if hasattr(keyboard, 'unhook_all_hotkeys') else keyboard.unhook_all()
        except Exception:
            pass
        self._kill_other_cap_solve_processes()
        os._exit(0)

    def on_force_exit_pressed(self):
        with self.shutdown_lock:
            self.is_shutting_down = True
            threading.Thread(target=self._force_shutdown_now, daemon=True).start()

    def run(self):
        import keyboard
        self.config = load_config()
        hotkeys_cfg = self.config.get('hotkeys', {})

        capture_key = hotkeys_cfg.get('capture', 'ctrl+shift+x')
        exit_key = hotkeys_cfg.get('exit', 'ctrl+shift+q')
        force_exit_key = hotkeys_cfg.get('force_exit', 'ctrl+shift+l')
        middle_click = _to_bool(hotkeys_cfg.get('middle_click', True), default=True)

        print("=== CHƯƠNG TRÌNH CAP-SOLVE ĐÃ KHỞI ĐỘNG (MISTRAL AI) ===")
        print(f"[*] Nhấn '{capture_key}' để giải bài.")
        print("[*] Nhấn 'Tab' để giải bài (dự phòng).")
        print("[*] Nhấn 'Ctrl+Shift+P' để bật/tắt proxy.")
        if middle_click:
            print("[*] Nhấn nút giữa chuột (scroll click) để giải bài.")
        print(f"[*] Nhấn '{force_exit_key}' để tắt ngay và kill sạch cap_solve*.")
        print(f"[*] Nhấn '{exit_key}' để thoát.\n")

        exit_event = threading.Event()
        def on_exit_request():
            exit_event.set()

        try:
            keyboard.add_hotkey(capture_key, self.on_hotkey_pressed, suppress=False)
            keyboard.add_hotkey('tab', self.on_hotkey_pressed, suppress=False)
            keyboard.add_hotkey('ctrl+shift+p', self.on_hotkey_pressed_proxy, suppress=False)
            keyboard.add_hotkey(force_exit_key, self.on_force_exit_pressed, suppress=False)
            keyboard.add_hotkey(exit_key, on_exit_request, suppress=False)
        except Exception as e:
            print(f"[-] Hotkey register error: {e}")

        # Polling fallback qua Win32 GetAsyncKeyState
        if os.name == 'nt':
            try:
                _install_keyboard_poll(capture_key, self.on_hotkey_pressed)
                _install_keyboard_poll(exit_key, on_exit_request)
                if middle_click:
                    _install_middle_click_hook(self.on_hotkey_pressed)
            except Exception as e:
                print(f"[-] Polling install error: {e}")

        show_started_popup(self.config)

        # Chờ phím thoát
        try:
            exit_event.wait()
        except (KeyboardInterrupt, SystemExit):
            pass

        print("[*] Đang đóng chương trình...")
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        _uninstall_middle_click_hook()
        _uninstall_keyboard_poll()
        close_current_popup(wait=True)

if __name__ == '__main__':
    app = CapSolveApp()
    app.run()
