import winreg
from PySide6.QtGui import QPalette, QColor, QFont
from PySide6.QtWidgets import QApplication

class ThemeColors:
    def __init__(self, is_dark):
        self.is_dark = is_dark
        
        if is_dark:
            self.bg_root = "#222222"
            self.bg_card = "#2B2B2B"
            self.bg_card_hover = "#3B3B3B"
            self.text_main = "#FFFFFF"
            self.text_dim = "#AAAAAA"
            self.success = "#6CCB5F"
            self.success_bg = "#2b7a2b"
            self.error = "#FF99A4"
            self.error_bg = "#a32a2a"
            self.primary = "#0078D4"
            self.border = "#444444"
        else:
            self.bg_root = "#F9F9F9"
            self.bg_card = "#FFFFFF"
            self.bg_card_hover = "#F0F0F0"
            self.text_main = "#000000"
            self.text_dim = "#666666"
            self.success = "#107C41"
            self.success_bg = "#107C41"
            self.error = "#C42B1C"
            self.error_bg = "#C42B1C"
            self.primary = "#0078D4"
            self.border = "#CCCCCC"

def is_dark_theme():
    try:
        registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
        key = winreg.OpenKey(registry, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except Exception:
        return False

def get_theme_colors():
    return ThemeColors(is_dark_theme())

def get_main_stylesheet():
    colors = get_theme_colors()
    return f"""
        QMainWindow, QWidget#central {{
            background-color: {colors.bg_root};
            color: {colors.text_main};
        }}
        QLabel, QCheckBox, QRadioButton {{
            color: {colors.text_main};
            background: transparent;
        }}
        QScrollArea {{
            background-color: {colors.bg_root};
            border: none;
        }}
        QWidget#scroll_content {{
            background-color: {colors.bg_root};
        }}
        QPushButton, QComboBox {{
            background-color: {colors.bg_card};
            color: {colors.text_main};
            border: 1px solid {colors.border};
            padding: 5px;
            border-radius: 3px;
        }}
        QPushButton:hover, QComboBox:hover {{
            background-color: {colors.bg_card_hover};
        }}
        QComboBox::drop-down {{
            border: none;
        }}
    """

def get_font(size=10, bold=False):
    # Use Segoe UI Variable Display with Microsoft YaHei UI as fallback
    font = QFont("Segoe UI Variable Display", size)
    if bold:
        font.setBold(True)
    return font
