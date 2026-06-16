import os
from datetime import date

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

_DEFAULT_KITE_PORT = 5010

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
QLabel#hint {
    color: #8b949e;
    font-size: 11px;
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
    "Zerodha Kite": "kite",
}


class _ConnectWorker(QThread):
    """Runs the broker login on a background thread.

    For Kite, optionally performs the interactive browser/redirect-capture flow
    first (``kite_auth=True``) to obtain a fresh request_token before connecting.
    """

    success = Signal()
    failure = Signal(str)

    def __init__(
        self,
        kite_auth: bool = False,
        login_url: str = "",
        port: int = _DEFAULT_KITE_PORT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._kite_auth = kite_auth
        self._login_url = login_url
        self._port = port

    def run(self) -> None:
        try:
            broker = BrokerManager.get_broker()

            if self._kite_auth:
                from broker.kite_auth import KiteAuthError, capture_request_token
                try:
                    request_token = capture_request_token(self._login_url, port=self._port)
                except KiteAuthError as exc:
                    self.failure.emit(str(exc))
                    return
                broker.set_request_token(request_token)

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
    """Login / configuration dialog (broker-aware: Angel + Zerodha Kite).

    Mode B (returning launch): shown when settings.yaml has saved credentials.
    Mode A (form): shown on first launch or when "Edit credentials" is clicked.

    Signals:
        login_successful(client_id, broker_name): emitted on successful connection.
    """

    login_successful = Signal(str, str)  # (client_id, broker_display)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("DemonEdge - Connect to Broker")
        self.setFixedWidth(440)
        self.setModal(True)
        self.setStyleSheet(_QSS)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self._saved_creds = _load_saved_credentials()
        self._is_first_launch = self._saved_creds is None
        self._came_from_mode_b = False
        self._worker: _ConnectWorker | None = None
        self._last_kite_cached = False  # track for expiry-fallback

        self._build_ui()

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

        title = QLabel("DemonEdge")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(title)

        sub = QLabel("Connect to your broker to begin trading")
        sub.setObjectName("subtitle")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(sub)
        outer.addSpacing(20)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)
        outer.addWidget(card)

        # Create the error label up front — _build_mode_a_page() triggers
        # _on_broker_changed() → _clear_error(), which needs it to exist.
        self._error_label = QLabel("")
        self._error_label.setObjectName("error")
        self._error_label.setWordWrap(True)
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setVisible(False)

        self._stack = QStackedWidget()
        card_layout.addWidget(self._stack)

        self._page_b = self._build_mode_b_page()
        self._page_a = self._build_mode_a_page()
        self._stack.addWidget(self._page_b)  # index 0
        self._stack.addWidget(self._page_a)  # index 1

        outer.addSpacing(10)
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
        self._broker_combo.currentTextChanged.connect(self._on_broker_changed)
        layout.addWidget(self._broker_combo)

        # ── Angel field group ──────────────────────────────────────────
        self._angel_group = QWidget()
        ag = QVBoxLayout(self._angel_group)
        ag.setContentsMargins(0, 0, 0, 0)
        ag.setSpacing(10)

        ag.addWidget(QLabel("API Key"))
        self._api_key_field = QLineEdit()
        self._api_key_field.setPlaceholderText("Your Angel API key")
        ag.addWidget(self._api_key_field)

        ag.addWidget(QLabel("Client ID"))
        self._client_id_field = QLineEdit()
        self._client_id_field.setPlaceholderText("Angel client/login ID")
        ag.addWidget(self._client_id_field)

        ag.addWidget(QLabel("Password"))
        self._password_field = QLineEdit()
        self._password_field.setPlaceholderText("Trading password")
        self._password_field.setEchoMode(QLineEdit.EchoMode.Password)
        ag.addWidget(self._password_field)

        ag.addWidget(QLabel("TOTP Secret"))
        self._totp_field = QLineEdit()
        self._totp_field.setPlaceholderText("Base32 TOTP secret key")
        self._totp_field.setEchoMode(QLineEdit.EchoMode.Password)
        ag.addWidget(self._totp_field)

        layout.addWidget(self._angel_group)

        # ── Kite field group ───────────────────────────────────────────
        self._kite_group = QWidget()
        kg = QVBoxLayout(self._kite_group)
        kg.setContentsMargins(0, 0, 0, 0)
        kg.setSpacing(10)

        kg.addWidget(QLabel("API Key"))
        self._kite_api_key_field = QLineEdit()
        self._kite_api_key_field.setPlaceholderText("Your Kite Connect api_key")
        kg.addWidget(self._kite_api_key_field)

        kg.addWidget(QLabel("API Secret"))
        self._kite_api_secret_field = QLineEdit()
        self._kite_api_secret_field.setPlaceholderText("Your Kite Connect api_secret")
        self._kite_api_secret_field.setEchoMode(QLineEdit.EchoMode.Password)
        kg.addWidget(self._kite_api_secret_field)

        kite_hint = QLabel(
            f"Clicking Connect opens your browser to log in to Zerodha. "
            f"Set your Kite app's redirect URL to http://127.0.0.1:{_DEFAULT_KITE_PORT}/"
        )
        kite_hint.setObjectName("hint")
        kite_hint.setWordWrap(True)
        kg.addWidget(kite_hint)

        layout.addWidget(self._kite_group)

        layout.addSpacing(4)

        self._save_checkbox = QCheckBox("Save credentials to settings.yaml")
        self._save_checkbox.setChecked(True)
        layout.addWidget(self._save_checkbox)

        layout.addSpacing(8)

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

        self._on_broker_changed(self._broker_combo.currentText())
        return page

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def _on_broker_changed(self, display_name: str) -> None:
        is_kite = _BROKER_MAP.get(display_name) == "kite"
        self._angel_group.setVisible(not is_kite)
        self._kite_group.setVisible(is_kite)
        self._clear_error()
        self.adjustSize()

    def _show_mode_b(self) -> None:
        creds = self._saved_creds or {}
        broker_name = creds.get("_broker_display", "Angel SmartAPI")
        label = creds.get("client_id") or broker_name
        self._b_welcome.setText(f"Welcome back, {label}")
        self._b_broker_label.setText(broker_name)
        self._stack.setCurrentIndex(0)
        self._clear_error()
        self.adjustSize()

    def _show_mode_a(self, prefill: dict | None) -> None:
        if prefill:
            display = prefill.get("_broker_display", "Angel SmartAPI")
            idx = self._broker_combo.findText(display)
            if idx >= 0:
                self._broker_combo.setCurrentIndex(idx)
            if prefill.get("_broker_key") == "kite":
                self._kite_api_key_field.setText(prefill.get("api_key", ""))
                self._kite_api_secret_field.setText(prefill.get("api_secret", ""))
            else:
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
        self.reject()

    def _on_cancel_mode_a(self) -> None:
        if self._came_from_mode_b:
            self._came_from_mode_b = False
            self._show_mode_b()
        elif self._is_first_launch:
            from PySide6.QtWidgets import QApplication
            self.reject()
            QApplication.quit()
        else:
            self.reject()

    def _on_connect_clicked(self) -> None:
        self._clear_error()

        if self._stack.currentIndex() == 0:
            creds = dict(self._saved_creds or {})
            broker_key = creds.get("_broker_key", "angel")
            should_save = False
        else:
            creds, broker_key, should_save = self._gather_form_creds()
            if creds is None:
                return

        # Instantiate and register the broker.
        try:
            BrokerManager.create_broker(broker_key, creds)
        except Exception as exc:
            self._show_error(f"Failed to initialise broker: {exc}")
            return

        # Decide whether the Kite interactive browser flow is needed.
        kite_auth = False
        login_url = ""
        port = int(creds.get("redirect_port", _DEFAULT_KITE_PORT) or _DEFAULT_KITE_PORT)
        self._last_kite_cached = False
        if broker_key == "kite":
            today = date.today().isoformat()
            has_valid_cache = bool(creds.get("access_token")) and (
                creds.get("access_token_date") == today
            )
            if has_valid_cache:
                self._last_kite_cached = True
            else:
                kite_auth = True
                try:
                    login_url = BrokerManager.get_broker().login_url()
                except Exception as exc:
                    self._show_error(f"Could not build Kite login URL: {exc}")
                    return

        self._pending_creds = creds
        self._pending_save = should_save
        self._set_connecting(True, kite_auth)

        self._worker = _ConnectWorker(
            kite_auth=kite_auth, login_url=login_url, port=port, parent=self
        )
        self._worker.success.connect(self._on_connect_success)
        self._worker.failure.connect(self._on_connect_failure)
        self._worker.start()

    def _gather_form_creds(self):
        """Read + validate the Mode A form. Returns (creds, broker_key, save) or (None,..)."""
        broker_display = self._broker_combo.currentText()
        broker_key = _BROKER_MAP.get(broker_display, "angel")
        should_save = self._save_checkbox.isChecked()

        if broker_key == "kite":
            api_key = self._kite_api_key_field.text().strip()
            api_secret = self._kite_api_secret_field.text().strip()
            if not all([api_key, api_secret]):
                self._show_error("API Key and API Secret are required.")
                return None, broker_key, should_save
            creds = {
                "api_key": api_key,
                "api_secret": api_secret,
                "redirect_port": _DEFAULT_KITE_PORT,
                "_broker_key": "kite",
                "_broker_display": broker_display,
            }
        else:
            api_key = self._api_key_field.text().strip()
            client_id = self._client_id_field.text().strip()
            password = self._password_field.text().strip()
            totp_secret = self._totp_field.text().strip()
            if not all([api_key, client_id, password, totp_secret]):
                self._show_error("All fields are required.")
                return None, broker_key, should_save
            creds = {
                "api_key": api_key,
                "client_id": client_id,
                "password": password,
                "totp_secret": totp_secret,
                "_broker_key": "angel",
                "_broker_display": broker_display,
            }
        return creds, broker_key, should_save

    def _on_connect_success(self) -> None:
        creds = dict(self._pending_creds)

        # For Kite, capture the freshly issued access_token for same-day reuse
        # and the user_id for the Mode B welcome line.
        if creds.get("_broker_key") == "kite":
            broker = BrokerManager.get_broker()
            creds["access_token"] = getattr(broker, "access_token", "")
            creds["access_token_date"] = getattr(broker, "access_token_date", "")
            try:
                profile = broker.get_profile()
                creds["client_id"] = profile.get("user_id", creds.get("client_id", ""))
            except Exception:
                pass
            # Always persist the refreshed token (even if the user didn't tick
            # "save"), but only when credentials were already being saved.
            if self._pending_save or self._saved_creds:
                _save_credentials(creds)
        elif self._pending_save:
            _save_credentials(creds)

        client_id = creds.get("client_id", "")
        broker_display = creds.get("_broker_display", "Angel SmartAPI")
        self.login_successful.emit(client_id, broker_display)
        self.accept()

    def _on_connect_failure(self, message: str) -> None:
        self._set_connecting(False)
        # If a cached Kite token was rejected, drop it so the next click logs in.
        if self._last_kite_cached and self._saved_creds:
            self._saved_creds["access_token"] = ""
            self._saved_creds["access_token_date"] = ""
            self._show_error(f"{message}\nClick Connect to log in again.")
        else:
            self._show_error(f"Connection failed: {message}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_connecting(self, connecting: bool, kite_auth: bool = False) -> None:
        if connecting and kite_auth:
            label = "Waiting for browser login…"
        elif connecting:
            label = "Connecting…"
        else:
            label = "Connect"
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

def _read_settings() -> dict:
    if not os.path.exists(_SETTINGS_PATH):
        return {}
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("Could not read settings.yaml: %s", exc)
        return {}


def _migrate_flat_angel(broker: dict) -> None:
    """Move legacy flat Angel keys under a nested ``angel`` sub-dict in place."""
    if "angel" in broker or "kite" in broker:
        return
    legacy_keys = ("api_key", "client_id", "password", "totp_secret")
    if any(k in broker for k in legacy_keys):
        broker["angel"] = {k: broker.pop(k) for k in legacy_keys if k in broker}


def _load_saved_credentials() -> dict | None:
    """Return saved credentials for the active broker, or None if incomplete."""
    data = _read_settings()
    broker = data.get("broker", {})
    if not broker:
        return None

    _migrate_flat_angel(broker)
    name = broker.get("name", "angel")
    sub = broker.get(name, {})

    if name == "kite":
        if not (sub.get("api_key") and sub.get("api_secret")):
            return None
        return {
            "_broker_key": "kite",
            "_broker_display": "Zerodha Kite",
            "api_key": sub["api_key"],
            "api_secret": sub["api_secret"],
            "redirect_port": sub.get("redirect_port", _DEFAULT_KITE_PORT),
            "access_token": sub.get("access_token", ""),
            "access_token_date": sub.get("access_token_date", ""),
            "client_id": sub.get("user_id", ""),
        }

    required = ("api_key", "client_id", "password", "totp_secret")
    if not all(sub.get(k) for k in required):
        return None
    return {
        "_broker_key": "angel",
        "_broker_display": "Angel SmartAPI",
        "api_key": sub["api_key"],
        "client_id": sub["client_id"],
        "password": sub["password"],
        "totp_secret": sub["totp_secret"],
    }


def _save_credentials(creds: dict) -> None:
    """Persist credentials for the active broker, preserving the other broker's."""
    data = _read_settings()
    broker = data.setdefault("broker", {})
    _migrate_flat_angel(broker)

    key = creds.get("_broker_key", "angel")
    broker["name"] = key
    sub = broker.setdefault(key, {})

    if key == "kite":
        sub["api_key"] = creds.get("api_key", "")
        sub["api_secret"] = creds.get("api_secret", "")
        sub["redirect_port"] = creds.get("redirect_port", _DEFAULT_KITE_PORT)
        sub["access_token"] = creds.get("access_token", "")
        sub["access_token_date"] = creds.get("access_token_date", "")
        if creds.get("client_id"):
            sub["user_id"] = creds["client_id"]
    else:
        sub["api_key"] = creds.get("api_key", "")
        sub["client_id"] = creds.get("client_id", "")
        sub["password"] = creds.get("password", "")
        sub["totp_secret"] = creds.get("totp_secret", "")

    data.setdefault("app", {"theme": "dark", "log_level": "INFO"})

    os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
    logger.info("Credentials saved to %s (broker=%s)", _SETTINGS_PATH, key)


def _broker_key_to_display(key: str) -> str:
    reverse = {v: k for k, v in _BROKER_MAP.items()}
    return reverse.get(key, "Angel SmartAPI")
