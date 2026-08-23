import sys
import os
import ctypes

# Add the project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from src.ui.main_window import MainWindow

VERSION = "1.0.9"

def main():
    print(f"Starting PTTApp v{VERSION}...")
    
    # 獨立的 AppUserModelID，避免跟其他 Python 程式 (例如 Tool Launcher) 擠在同一個工作列群組
    try:
        myappid = 'antigravity.pttapp.v1'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon', 'mic.png')
    app.setWindowIcon(QIcon(icon_path))
    
    window = MainWindow()
    # Add version to window title (assuming setWindowTitle exists in MainWindow or we can do it here)
    window.setWindowTitle(f"按鍵發話控制器 v{VERSION}")
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
