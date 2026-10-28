import os
import sys

def get_base_dir() -> str:
    """Trả về thư mục gốc của chương trình (khi chạy exe hoặc script)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def resolve_runtime_path(*parts: str) -> str:
    """Tìm đường dẫn tài nguyên ưu tiên base_dir, fallback sys._MEIPASS."""
    base_dir = get_base_dir()
    primary = os.path.join(base_dir, *parts)
    if os.path.exists(primary):
        return primary
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        meipass = getattr(sys, '_MEIPASS')
        alt = os.path.join(meipass, *parts)
        if os.path.exists(alt):
            return alt
        internal = os.path.join(meipass, '_internal', *parts)
        if os.path.exists(internal):
            return internal
    return primary

def resolve_settings_path() -> str:
    """Tìm file config settings.json theo các vị trí ưu tiên."""
    base_dir = get_base_dir()
    candidates = [
        os.path.join(base_dir, 'settings.json'),
        os.path.join(base_dir, 'config', 'settings.json'),
        os.path.join(base_dir, '_internal', 'config', 'settings.json')
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[1]
