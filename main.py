import sys
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.app_state import AppState
from app.main_window import MainWindow
from app.theme import apply_theme
from feed.market_feed import MarketFeed
from utils.config import Config
from utils.logger import configure_level, get_logger


def _qt_message_handler(msg_type: QtMsgType, _context, message: str) -> None:
    """Suppress noisy Qt internal warnings that would pollute the log viewer."""
    # QFont::setPointSize warnings produced by pyqtgraph / PySide6 internals
    if "QFont::setPointSize" in message or "point size" in message:
        return
    # Let everything else through to stderr (default behaviour)
    if msg_type in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        print(f"Qt: {message}", file=sys.stderr)

# pyqtgraph global config — must be set before any pg widget or QApplication is created
pg.setConfigOption('background', '#0d1117')
pg.setConfigOption('foreground', '#8b949e')
pg.setConfigOption('antialias', True)


def main() -> None:
    # Suppress noisy Qt internal warnings before the app loop starts
    qInstallMessageHandler(_qt_message_handler)

    # Configure logging — best-effort, settings.yaml may not exist on first launch
    try:
        log_level = Config.get("app.log_level", "INFO")
        configure_level(log_level)
    except FileNotFoundError:
        pass

    logger = get_logger(__name__)
    logger.info("DemonEdge starting…")

    # Initialise non-Qt singletons before QApplication
    _ = AppState
    _ = MarketFeed

    app = QApplication(sys.argv)
    app.setApplicationName("DemonEdge")

    # Set app icon (shown in taskbar / window title bar)
    icon_path = Path(__file__).resolve().parent / "icons" / "app_icon.png"
    app.setWindowIcon(QIcon(str(icon_path)))

    # Apply global dark theme before any windows are created
    apply_theme(app)

    # Install Qt logging handler so LogViewerWidget receives all log records
    from widgets.log_viewer.qt_log_handler import install_qt_handler
    install_qt_handler()

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
