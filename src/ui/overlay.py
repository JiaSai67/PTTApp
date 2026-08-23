import os
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

class MicOffOverlay(QWidget):
    def __init__(self, config_manager):
        super().__init__()
        self.config = config_manager
        
        # Frameless, tool window (no taskbar), always on top, and ignores all mouse events (transparent for input)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.icon_label = QLabel()
        
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.pixmap_on = QPixmap(os.path.join(base_dir, 'icon', 'mic_on.png')).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.pixmap_off = QPixmap(os.path.join(base_dir, 'icon', 'mic_off.png')).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        
        self.icon_label.setPixmap(self.pixmap_off)
        layout.addWidget(self.icon_label)
        
        # Load position or default
        pos_x = self.config.get('icon_pos_x')
        pos_y = self.config.get('icon_pos_y')
        
        if pos_x is not None and pos_y is not None:
            self.move(pos_x, pos_y)
        else:
            self.position_top_center()

    def set_state(self, is_unmuted):
        if is_unmuted:
            self.icon_label.setPixmap(self.pixmap_on)
        else:
            self.icon_label.setPixmap(self.pixmap_off)

    def position_top_center(self):
        screen_geometry = self.screen().geometry()
        x = screen_geometry.x() + (screen_geometry.width() - 64) // 2
        y = screen_geometry.y() + 20  # 20 pixels from the top edge
        self.move(x, y)
        self.config.set('icon_pos_x', x)
        self.config.set('icon_pos_y', y)
