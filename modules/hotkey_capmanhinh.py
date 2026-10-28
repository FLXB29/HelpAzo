import ctypes
import json
import os
import struct
import sys
import traceback
from datetime import datetime
import keyboard
from PIL import Image, ImageGrab

from modules.path_utils import get_base_dir, resolve_settings_path

CONFIG_PATH = resolve_settings_path()
_LOG_FILE = os.path.join(get_base_dir(), 'debug_cap.log')

def _log(msg: str):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')
    line = f"[{timestamp}] {msg}\n"
    try:
        with open(_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        pass
    print(line, end='')

# Thử bật DPI awareness để chụp ảnh đúng độ phân giải màn hình Windows
try:
    if sys.platform == 'win32':
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        if sys.platform == 'win32':
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

def load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_bmp_raw(filepath, pixels, width, height, bgr_bytes_per_pixel=3):
    """Ghi trực tiếp file BMP từ buffer pixel BGR/BGRA."""
    row_size = ((width * bgr_bytes_per_pixel + 3) // 4) * 4
    pixel_array_size = row_size * height
    offset = 54
    file_size = offset + pixel_array_size

    with open(filepath, 'wb') as f:
        # BMP Header (14 bytes)
        f.write(b'BM')
        f.write(struct.pack('<I', file_size))
        f.write(struct.pack('<H', 0))
        f.write(struct.pack('<H', 0))
        f.write(struct.pack('<I', offset))
        # DIB Header (40 bytes)
        f.write(struct.pack('<I', 40))
        f.write(struct.pack('<i', width))
        f.write(struct.pack('<i', height))
        f.write(struct.pack('<H', 1))
        f.write(struct.pack('<H', bgr_bytes_per_pixel * 8))
        f.write(struct.pack('<I', 0))
        f.write(struct.pack('<I', pixel_array_size))
        f.write(struct.pack('<i', 0))
        f.write(struct.pack('<i', 0))
        f.write(struct.pack('<I', 0))
        f.write(struct.pack('<I', 0))
        f.write(pixels)

def _capture_with_win32(filepath):
    """Fallback chụp màn hình bằng Win32 GDI API."""
    _log("[win32] bat dau")
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd = user32.GetDesktopWindow()
    hdc = user32.GetDC(hwnd)
    hmemdc = gdi32.CreateCompatibleDC(hdc)

    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    _log(f"[win32] {screen_w}x{screen_h}")

    hbitmap = gdi32.CreateCompatibleBitmap(hdc, screen_w, screen_h)
    gdi32.SelectObject(hmemdc, hbitmap)
    # SRCCOPY = 0x00CC0020
    gdi32.BitBlt(hmemdc, 0, 0, screen_w, screen_h, hdc, 0, 0, 0x00CC0020)

    # BITMAPINFO
    bmi = struct.pack('IiiHHIIiiII', 40, screen_w, screen_h, 1, 32, 0, screen_w * screen_h * 4, 0, 0, 0, 0)
    pixel_buf = ctypes.create_string_buffer(screen_w * screen_h * 4)

    try:
        gdi32.GetDIBits(hmemdc, hbitmap, 0, screen_h, pixel_buf, bmi, 0)
        # Chuyển BGRA sang BGR (BMP bottom-up)
        raw_bgra = pixel_buf.raw
        row_size_bgr = ((screen_w * 3 + 3) // 4) * 4
        padding = row_size_bgr - (screen_w * 3)
        bgr_data = bytearray()
        for y in range(screen_h):
            row_start = y * screen_w * 4
            for x in range(screen_w):
                px = row_start + x * 4
                bgr_data.extend(raw_bgra[px:px+3])
            if padding:
                bgr_data.extend(b'\x00' * padding)

        _save_bmp_raw(filepath, bytes(bgr_data), screen_w, screen_h, 3)
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            _log(f"[win32] thanh cong | {os.path.getsize(filepath)} bytes")
            return filepath
        else:
            _log("[win32] file rong")
            return None
    except Exception as e:
        _log(f"[win32] LOI: {e}\n{traceback.format_exc()}")
        return None
    finally:
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(hmemdc)
        user32.ReleaseDC(hwnd, hdc)

class ScreenCapturer:
    def __init__(self, config=None):
        self.config = config or load_config()
        base_dir = get_base_dir()
        sc_dir = self.config.get('app', {}).get('screenshot_dir', 'screenshots')
        self.save_dir = os.path.join(base_dir, sc_dir)
        os.makedirs(self.save_dir, exist_ok=True)

    def capture_full_screen(self):
        frozen = getattr(sys, 'frozen', False)
        _log(f"[capture] bat dau | save_dir={self.save_dir} | frozen={frozen}")
        os.makedirs(self.save_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = os.path.join(self.save_dir, f"capture_{timestamp}.bmp")
        _log(f"[capture] filepath={filepath}")

        # Cách 1: PIL ImageGrab
        try:
            _log("[capture] Cach 1: ImageGrab.grab...")
            screenshot = ImageGrab.grab(all_screens=True)
            _log(f"[capture] ImageGrab OK: {type(screenshot).__name__}")
            screenshot_rgb = screenshot.convert('RGB')
            w, h = screenshot_rgb.size
            raw_rgb = screenshot_rgb.tobytes()
            _log(f"[capture] raw bytes: {len(raw_rgb)}")

            # Ghi file BMP (BGR bottom-up)
            row_pad = ((w * 3 + 3) // 4) * 4 - (w * 3)
            bgr_rows = bytearray()
            for y in range(h - 1, -1, -1):
                row_start = y * w * 3
                row = raw_rgb[row_start:row_start + w * 3]
                for i in range(0, len(row), 3):
                    r = row[i]
                    g = row[i + 1]
                    b = row[i + 2]
                    bgr_rows.extend((b, g, r))
                if row_pad:
                    bgr_rows.extend(b'\x00' * row_pad)

            _save_bmp_raw(filepath, bytes(bgr_rows), w, h, 3)
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                _log(f"[capture] THANH CONG (ImageGrab): {os.path.getsize(filepath)} bytes")
                return filepath
            else:
                _log("[capture] ImageGrab LOI: empty file")
        except Exception as e:
            _log(f"[capture] ImageGrab LOI: {e}\n{traceback.format_exc()}")

        # Cách 2: Win32 GDI fallback
        try:
            _log("[capture] Cach 2: Win32 fallback...")
            res = _capture_with_win32(filepath)
            if res:
                _log(f"[capture] THANH CONG (Win32): {os.path.getsize(filepath)} bytes")
                return res
        except Exception as e:
            _log(f"[capture] THAT BAI: {e}")

        _log("[capture] LOI NGHIEM TRONG: Khong the chup man hinh bang bat ky phuong phap nao")
        return None

    def start_listening(self):
        hotkeys_cfg = self.config.get('hotkeys', {})
        hotkey = hotkeys_cfg.get('capture', 'f8')
        exit_key = hotkeys_cfg.get('exit', 'esc')
        print(f"[*] Nhan '{hotkey}' de chup man hinh.")
        print(f"[*] Nhan '{exit_key}' de thoat.")
        keyboard.add_hotkey(hotkey, self.capture_full_screen)
        keyboard.wait(exit_key)
        keyboard.unhook_all()
        print("\n[*] Da thoat.")
