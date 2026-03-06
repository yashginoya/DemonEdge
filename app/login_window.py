import os

import yaml
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from broker.base_broker import BrokerAPIError
from broker.broker_manager import BrokerManager
from utils.logger import get_logger

logger = get_logger(__name__)

_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "settings.yaml"
)

_QSS = """
QDialog {
    background-color: #0d1117;
}
QLabel {
    color: #c9d1d9;
    font-size: 13px;
}
QLabel#title {
    color: #e6edf3;
    font-size: 18px;
    font-weight: bold;
}
QLabel#subtitle {
    color: #8b949e;
    font-size: 12px;
}
QLabel#welcome {
    color: #e6edf3;
    font-size: 15px;
    font-weight: bold;
}
QLabel#error {
    color: #f85149;
    font-size: 12px;
}
QLineEdit {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    color: #c9d1d9;
    padding: 8px 10px;
    font-size: 13px;
    font-family: "Consolas", "Courier New", monospace;
}
QLineEdit:focus {
    border: 1px solid #388bfd;
}
QComboBox {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    color: #c9d1d9;
    padding: 8px 10px;
    font-size: 13px;
    min-height: 36px;
}
QComboBox::drop-down {
    border: none;
}
QComboBox QAbstractItemView {
    background-color: #161b22;
    color: #c9d1d9;
    selection-background-color: #1f6feb;
    border: 1px solid #30363d;
}
QCheckBox {
    color: #8b949e;
    font-size: 12px;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #30363d;
    border-radius: 3px;
    background-color: #161b22;
}
QCheckBox::indicator:checked {
    background-color: #1f6feb;
    border-color: #1f6feb;
}
QPushButton#connect {
    background-color: #238636;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 10px 24px;
    font-size: 14px;
    font-weight: bold;
    min-height: 38px;
}
QPushButton#connect:hover {
    background-color: #2ea043;
}
QPushButton#connect:disabled {
    background-color: #21262d;
    color: #484f58;
}
QPushButton#cancel {
    background-color: transparent;
    color: #8b949e;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 10px 24px;
    font-size: 13px;
    min-height: 38px;
}
QPushButton#cancel:hover {
    background-color: #21262d;
    color: #c9d1d9;
}
QPushButton#link {
    background-color: transparent;
    color: #388bfd;
    border: none;
    padding: 0;
    font-size: 12px;
    text-align: left;
}
QPushButton#link:hover {
    color: #58a6ff;
}
QFrame#card {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
}
QFrame#divider {
    background-color: #30363d;
    max-height: 1px;
}
"""

_BROKER_MAP = {
    "Angel SmartAPI": "angel",
}


class _ConnectWorker(QThread):
    """Runs broker.connect() on a background thread."""

    success = Signal()
    failure = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        try:
            broker = BrokerManager.get_broker()
            ok = broker.connect()
            if ok:
                self.success.emit()
            else:
                self.failure.emit("Connection returned False — check credentials.")
        except BrokerAPIError as exc:
            self.failure.emit(str(exc))
        except Exception as exc:
            logger.exception("Unexpected error during connect")
            self.failure.emit(f"Unexpected error: {exc}")


class LoginWindow(QDialog):
    """Login / configuration dialog.

    Mode B (returning launch): shown when settings.yaml exists with credentials.
    Mode A (form): shown on first launch or when "Edit credentials" is clicked.

    Signals:
        login_successful(client_id, broker_name): emitted on successful connection.
    """

    login_successful = Signal(str, str)  # (client_id, broker_name)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect to Broker")
        self.setFixedWidth(440)
        self.setModal(True)
        self.setStyleSheet(_QSS)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self._saved_creds = _load_saved_credentials()
        self._is_first_launch = self._saved_creds is None
        self._came_from_mode_b = False
        self._worker: _ConnectWorker | None = None

        self._build_ui()

        # Start in the appropriate mode
        if self._is_first_launch:
            self._show_mode_a(prefill=None)
        else:
            self._show_mode_b()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(0)

        # Title row
        title = QLabel("Trading Terminal")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(title)

        sub = QLabel("Connect to your broker to begin trading")
        sub.setObjectName("subtitle")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(sub)
        outer.addSpacing(20)

        # Card frame
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)
        outer.addWidget(card)

        # Stacked pages: 0 = Mode B, 1 = Mode A
        self._stack = QStackedWidget()
        card_layout.addWidget(self._stack)

        self._page_b = self._build_mode_b_page()
        self._page_a = self._build_mode_a_page()
        self._stack.addWidget(self._page_b)  # index 0
        self._stack.addWidget(self._page_a)  # index 1

        # Error label (shared, below card)
        outer.addSpacing(10)
        self._error_label = QLabel("")
        self._error_label.setObjectName("error")
        self._error_label.setWordWrap(True)
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setVisible(False)
        outer.addWidget(self._error_label)
        outer.addStretch()

    def _build_mode_b_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self._b_welcome = QLabel("")
        self._b_welcome.setObjectName("welcome")
        self._b_welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._b_welcome)

        self._b_broker_label = QLabel("")
        self._b_broker_label.setObjectName("subtitle")
        self._b_broker_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._b_broker_label)

        layout.addSpacing(8)

        self._b_connect_btn = QPushButton("Connect")
        self._b_connect_btn.setObjectName("connect")
        self._b_connect_btn.clicked.connect(self._on_connect_clicked)
        layout.addWidget(self._b_connect_btn)

        self._b_cancel_btn = QPushButton("Cancel")
        self._b_cancel_btn.setObjectName("cancel")
        self._b_cancel_btn.clicked.connect(self._on_cancel_mode_b)
        layout.addWidget(self._b_cancel_btn)

        edit_btn = QPushButton("Edit credentials")
        edit_btn.setObjectName("link")
        edit_btn.setFlat(True)
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.clicked.connect(self._on_edit_credentials)
        layout.addWidget(edit_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        return page

    def _build_mode_a_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Broker selector
        layout.addWidget(QLabel("Broker"))
        self._broker_combo = QComboBox()
        for display_name in _BROKER_MAP:
            self._broker_combo.addItem(display_name)
        layout.addWidget(self._broker_combo)

        # API Key
        layout.addWidget(QLabel("API Key"))
        self._api_key_field = QLineEdit()
        self._api_key_field.setPlaceholderText("Your Angel API key")
        layout.addWidget(self._api_key_field)

        # Client ID
        layout.addWidget(QLabel("Client ID"))
        self._client_id_field = QLineEdit()
        self._client_id_field.setPlaceholderText("Angel client/login ID")
        layout.addWidget(self._client_id_field)

        # Password
        layout.addWidget(QLabel("Password"))
        self._password_field = QLineEdit()
        self._password_field.setPlaceholderText("Trading password")
        self._password_field.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._password_field)

        # TOTP Secret
        layout.addWidget(QLabel("TOTP Secret"))
        self._totp_field = QLineEdit()
        self._totp_field.setPlaceholderText("Base32 TOTP secret key")
        self._totp_field.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._totp_field)

        layout.addSpacing(4)

        # Save checkbox
        self._save_checkbox = QCheckBox("Save credentials to settings.yaml")
        self._save_checkbox.setChecked(True)
        layout.addWidget(self._save_checkbox)

        layout.addSpacing(8)

        # Buttons row
        btn_row = QHBoxLayout()
        self._a_cancel_btn = QPushButton("Cancel")
        self._a_cancel_btn.setObjectName("cancel")
        self._a_cancel_btn.clicked.connect(self._on_cancel_mode_a)
        btn_row.addWidget(self._a_cancel_btn)

        self._a_connect_btn = QPushButton("Connect")
        self._a_connect_btn.setObjectName("connect")
        self._a_connect_btn.clicked.connect(self._on_connect_clicked)
        btn_row.addWidget(self._a_connect_btn)

        layout.addLayout(btn_row)
        return page

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def _show_mode_b(self) -> None:
        creds = self._saved_creds or {}
        client_id = creds.get("client_id", "")
        broker_name = creds.get("_broker_display", "Angel SmartAPI")
        self._b_welcome.setText(f"Welcome back, {client_id}")
        self._b_broker_label.setText(broker_name)
        self._stack.setCurrentIndex(0)
        self._clear_error()
        self.adjustSize()

    def _show_mode_a(self, prefill: dict | None) -> None:
        if prefill:
            self._api_key_field.setText(prefill.get("api_key", ""))
            self._client_id_field.setText(prefill.get("client_id", ""))
            self._password_field.setText(prefill.get("password", ""))
            self._totp_field.setText(prefill.get("totp_secret", ""))
        self._stack.setCurrentIndex(1)
        self._clear_error()
        self.adjustSize()

    def _on_edit_credentials(self) -> None:
        self._came_from_mode_b = True
        self._show_mode_a(prefill=self._saved_creds)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_cancel_mode_b(self) -> None:
        """Cancel from Mode B — close dialog, stay disconnected."""
        self.reject()

    def _on_cancel_mode_a(self) -> None:
        """Cancel from Mode A form."""
        if self._came_from_mode_b:
            # Go back to returning-user view
            self._came_from_mode_b = False
            self._show_mode_b()
        elif self._is_first_launch:
            # First launch cancel → signal app to exit
            from PySide6.QtWidgets import QApplication
            self.reject()
            QApplication.quit()
        else:
            self.reject()

    def _on_connect_clicked(self) -> None:
        self._clear_error()

        # Gather credentials
        if self._stack.currentIndex() == 0:
            # Mode B — use saved credentials
            creds = self._saved_creds or {}
            broker_key = creds.get("_broker_key", "angel")
            should_save = False
        else:
            # Mode A — read from form
            api_key = self._api_key_field.text().strip()
            client_id = self._client_id_field.text().strip()
            password = self._password_field.text().strip()
            totp_secret = self._totp_field.text().strip()
            broker_display = self._broker_combo.currentText()
            broker_key = _BROKER_MAP.get(broker_display, "angel")

            if not all([api_key, client_id, password, totp_secret]):
                self._show_error("All fields are required.")
                return

            creds = {
                "api_key": api_key,
                "client_id": client_id,
                "password": password,
                "totp_secret": totp_secret,
                "_broker_key": broker_key,
                "_broker_display": broker_display,
            }
            should_save = self._save_checkbox.isChecked()

        # Instantiate and register the broker
        try:
            BrokerManager.create_broker(broker_key, creds)
        except Exception as exc:
            self._show_error(f"Failed to initialise broker: {exc}")
            return

        self._pending_creds = creds
        self._pending_save = should_save

        # Disable buttons, show "Connecting…"
        self._set_connecting(True)

        self._worker = _ConnectWorker(self)
        self._worker.success.connect(self._on_connect_success)
        self._worker.failure.connect(self._on_connect_failure)
        self._worker.start()

    def _on_connect_success(self) -> None:
        creds = self._pending_creds
        if self._pending_save:
            _save_credentials(creds)

        client_id = creds.get("client_id", "")
        broker_display = creds.get("_broker_display", "Angel SmartAPI")

        self.login_successful.emit(client_id, broker_display)
        self.accept()

    def _on_connect_failure(self, message: str) -> None:
        self._set_connecting(False)
        self._show_error(f"Connection failed: {message}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_connecting(self, connecting: bool) -> None:
        label = "Connecting…" if connecting else "Connect"
        if self._stack.currentIndex() == 0:
            self._b_connect_btn.setText(label)
            self._b_connect_btn.setEnabled(not connecting)
            self._b_cancel_btn.setEnabled(not connecting)
        else:
            self._a_connect_btn.setText(label)
            self._a_connect_btn.setEnabled(not connecting)
            self._a_cancel_btn.setEnabled(not connecting)

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)

    def _clear_error(self) -> None:
        self._error_label.setText("")
        self._error_label.setVisible(False)


# ------------------------------------------------------------------
# Config I/O helpers (module-level, not part of the dialog class)
# ------------------------------------------------------------------

def _load_saved_credentials() -> dict | None:
    """Return saved credentials if settings.yaml exists and has broker credentials."""
    if not os.path.exists(_SETTINGS_PATH):
        return None
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        broker = data.get("broker", {})
        required = ("api_key", "client_id", "password", "totp_secret")
        if not all(broker.get(k) for k in required):
            return None
        return {
            "api_key": broker["api_key"],
            "client_id": broker["client_id"],
            "password": broker["password"],
            "totp_secret": broker["totp_secret"],
            "_broker_key": broker.get("name", "angel"),
            "_broker_display": _broker_key_to_display(broker.get("name", "angel")),
        }
    except Exception as exc:
        logger.warning("Could not load saved credentials: %s", exc)
        return None


def _save_credentials(creds: dict) -> None:
    """Write credentials to config/settings.yaml (full structure)."""
    os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
    data = {
        "broker": {
            "name": creds.get("_broker_key", "angel"),
            "api_key": creds.get("api_key", ""),
            "client_id": creds.get("client_id", ""),
            "password": creds.get("password", ""),
            "totp_secret": creds.get("totp_secret", ""),
        },
        "app": {
            "theme": "dark",
            "log_level": "INFO",
        },
    }
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
    logger.info("Credentials saved to %s", _SETTINGS_PATH)


def _broker_key_to_display(key: str) -> str:
    reverse = {v: k for k, v in _BROKER_MAP.items()}
    return reverse.get(key, "Angel SmartAPI")
