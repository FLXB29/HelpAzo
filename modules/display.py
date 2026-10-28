import threading
import tkinter as tk
from tkinter import font
import keyboard

_current_popup = None
_popup_lock = threading.Lock()
_ui_root = None
_ui_thread = None
_ui_ready = threading.Event()

def _ui_loop():
    global _ui_root
    try:
        _ui_root = tk.Tk()
        _ui_root.withdraw()
        _ui_ready.set()
        _ui_root.mainloop()
    except Exception:
        pass

def _ensure_ui_thread():
    global _ui_thread
    if _ui_thread is None or not _ui_thread.is_alive():
        _ui_ready.clear()
        _ui_thread = threading.Thread(target=_ui_loop, daemon=True)
        _ui_thread.start()
        _ui_ready.wait(timeout=3)

def _run_on_ui_thread(func):
    _ensure_ui_thread()
    if _ui_root:
        _ui_root.after(0, func)

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

def _get_visual_settings(config):
    app_cfg = config.get('app', {}) if isinstance(config, dict) else {}
    theme = str(app_cfg.get('theme', 'light')).lower()
    show_details = _to_bool(app_cfg.get('show_details', True), default=True)

    try:
        popup_scale_val = float(app_cfg.get('popup_scale', 92))
    except (TypeError, ValueError):
        popup_scale_val = 92.0
    popup_scale_val = max(5.0, min(300.0, popup_scale_val))
    scale = popup_scale_val / 100.0

    # popup_opacity / popup_alpha
    opacity_raw = app_cfg.get('popup_opacity', app_cfg.get('popup_alpha', 62))
    try:
        popup_alpha_val = float(opacity_raw)
    except (TypeError, ValueError):
        popup_alpha_val = 62.0

    if popup_alpha_val > 1.0:
        popup_alpha = max(0.05, min(1.0, popup_alpha_val / 100.0))
    else:
        popup_alpha = max(0.05, min(1.0, popup_alpha_val))

    if theme == 'dark':
        default_bg = '#1e1e1e'
        default_fg = '#f0f0f0'
    else:
        default_bg = '#f5f5f5'
        default_fg = '#202020'

    bg_color = app_cfg.get('popup_bg', default_bg)
    fg_color = app_cfg.get('popup_fg', default_fg)

    try:
        auto_close_seconds = float(app_cfg.get('auto_close_seconds', 0))
    except (TypeError, ValueError):
        auto_close_seconds = 0.0

    return {
        'show_details': show_details,
        'scale': scale,
        'popup_alpha': popup_alpha,
        'bg_color': bg_color,
        'fg_color': fg_color,
        'auto_close_seconds': auto_close_seconds
    }

class AnswerOverlay:
    def __init__(self, root, data, config):
        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.attributes('-topmost', True)
        self._closed = False

        visuals = _get_visual_settings(config)
        self.window.attributes('-alpha', visuals['popup_alpha'])
        self.window.configure(bg=visuals['bg_color'])

        scale = visuals['scale']
        show_details = visuals['show_details']

        content_font = font.Font(
            family='Segoe UI',
            size=max(8, round(10 * scale)),
            weight='normal'
        )

        wrapper = tk.Frame(self.window, bg=visuals['bg_color'], bd=0, highlightthickness=0)
        wrapper.pack(fill='both', expand=True, padx=10, pady=8)

        results = data.get('results', []) if isinstance(data, dict) else []
        for item in results:
            if not isinstance(item, dict):
                continue
            number = str(item.get('number', '')).strip()
            answer = str(item.get('answer', '')).strip()
            details = str(item.get('details', '')).strip()

            if show_details and details:
                label_text = f"{number}: {answer} — {details}"
            else:
                label_text = f"{number}: {answer}"

            lbl = tk.Label(
                wrapper,
                text=label_text,
                bg=visuals['bg_color'],
                fg=visuals['fg_color'],
                font=content_font,
                justify='left',
                anchor='w'
            )
            lbl.pack(fill='x', anchor='w', pady=3)

        close_key = config.get('hotkeys', {}).get('close_popup', 'space') if isinstance(config, dict) else 'space'
        try:
            self.close_hotkey_id = keyboard.add_hotkey(close_key, self.close_window, suppress=False)
        except Exception:
            self.close_hotkey_id = None

        self.window.bind('<Button-1>', lambda e: self.close_window())

        self.window.update_idletasks()
        width = self.window.winfo_width()
        height = self.window.winfo_height()
        screen_height = self.window.winfo_screenheight()
        self.window.geometry(f"{width}x{height}+20+{max(20, screen_height - height - 80)}")

        auto_close_sec = visuals.get('auto_close_seconds', 0.0)
        if auto_close_sec and auto_close_sec > 0:
            self.window.after(int(auto_close_sec * 1000), self.close_window)

    def close_window(self):
        if self._closed:
            return
        self._closed = True
        if self.close_hotkey_id is not None:
            try:
                keyboard.remove_hotkey(self.close_hotkey_id)
            except Exception:
                pass
        try:
            self.window.destroy()
        except Exception:
            pass

class StatusOverlay:
    def __init__(self, root, config, text='Started, hide in 3s', dot_color='#22c55e', close_delay=3000):
        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.attributes('-topmost', True)
        self._closed = False

        visuals = _get_visual_settings(config)
        self.window.attributes('-alpha', visuals['popup_alpha'])
        self.window.configure(bg=visuals['bg_color'])

        scale = visuals['scale']
        wrapper = tk.Frame(self.window, bg=visuals['bg_color'], bd=1)
        wrapper.pack(fill='both', expand=True, padx=10, pady=8)

        row = tk.Frame(wrapper, bg=visuals['bg_color'])
        row.pack(fill='x', anchor='w')

        dot_font = font.Font(family='Segoe UI', size=max(9, round(14 * scale)), weight='bold')
        text_font = font.Font(family='Segoe UI', size=max(8, round(11 * scale)), weight='normal')

        dot_lbl = tk.Label(row, text='● ', fg=dot_color, bg=visuals['bg_color'], font=dot_font)
        dot_lbl.pack(side='left')

        text_lbl = tk.Label(row, text=text, fg=visuals['fg_color'], bg=visuals['bg_color'], font=text_font)
        text_lbl.pack(side='left')

        self.window.bind('<Button-1>', lambda e: self.close_window())

        self.window.update_idletasks()
        width = self.window.winfo_width()
        height = self.window.winfo_height()
        screen_height = self.window.winfo_screenheight()
        self.window.geometry(f"{width}x{height}+20+{max(20, screen_height - height - 120)}")

        if close_delay and close_delay > 0:
            self.window.after(close_delay, self.close_window)

    def close_window(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.window.destroy()
        except Exception:
            pass

def close_current_popup(wait=True, timeout=None):
    event = threading.Event()
    def _close():
        global _current_popup
        with _popup_lock:
            if _current_popup is not None:
                try:
                    _current_popup.close_window()
                except Exception:
                    pass
                _current_popup = None
        event.set()
    _run_on_ui_thread(_close)
    if wait:
        event.wait(timeout=timeout)

def show_answers_popup(data, config):
    def _show():
        global _current_popup
        with _popup_lock:
            if _current_popup is not None:
                try:
                    _current_popup.close_window()
                except Exception:
                    pass
                _current_popup = None
            _current_popup = AnswerOverlay(_ui_root, data, config)
    _run_on_ui_thread(_show)

def show_started_popup(config):
    def _show():
        global _current_popup
        with _popup_lock:
            if _current_popup is not None:
                try:
                    _current_popup.close_window()
                except Exception:
                    pass
                _current_popup = None
            _current_popup = StatusOverlay(_ui_root, config, text='Started, hide in 3s', dot_color='#22c55e', close_delay=3000)
    _run_on_ui_thread(_show)

def show_notification_popup(text, dot_color, config):
    def _show():
        global _current_popup
        with _popup_lock:
            if _current_popup is not None:
                try:
                    _current_popup.close_window()
                except Exception:
                    pass
                _current_popup = None
            _current_popup = StatusOverlay(_ui_root, config, text=text, dot_color=dot_color, close_delay=4000)
    _run_on_ui_thread(_show)
