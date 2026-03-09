import sys
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.app_state import AppState
from app.main_window import MainWindow
from app.theme import apply_theme
from feed.market_feed import MarketFeed
from utils.config import Config
from utils.logger import configure_level, get_logger

# pyqtgraph global config — must be set before any pg widget or QApplication is created
pg.setConfigOption('background', '#0d1117')
pg.setConfigOption('foreground', '#8b949e')
pg.setConfigOption('antialias', True)


def main() -> None:
    # Configure logging — best-effort, settings.yaml may not exist on first launch
    try:
        log_level = Config.get("app.log_level", "INFO")
        configure_level(log_level)
    except FileNotFoundError:
        pass

    logger = get_logger(__name__)
    logger.info("Trading Terminal starting…")

    # Initialise non-Qt singletons before QApplication
    _ = AppState
    _ = MarketFeed

    app = QApplication(sys.argv)
    app.setApplicationName("Trading Terminal")

    # Set app icon (shown in taskbar / window title bar)
    icon_path = Path(__file__).resolve().parent / "icons" / "app_icon.png"
    app.setWindowIcon(QIcon(str(icon_path)))

    # Apply global dark theme before any windows are created
    apply_theme(app)

    window = MainWindow()
    window.show()

    # Modal login on top of the already-visible main window.
    # On first-launch cancel: LoginWindow calls QApplication.quit() directly.
    # On returning-user cancel: dialog closes, terminal stays in disconnected state.
    logged_in = window.show_login()

    if not logged_in and not AppState.is_connected():
        logger.info("Login cancelled — exiting.")
        sys.exit(0)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
