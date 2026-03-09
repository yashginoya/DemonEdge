from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class OrderConfirmationDialog(QDialog):
    """Pre-trade confirmation popup.

    Shows a brief order summary. ``Confirm`` returns ``QDialog.Accepted``;
    ``Cancel`` returns ``QDialog.Rejected``. Not dismissable by clicking outside.
    """

    def __init__(
        self,
        side: str,
        quantity: int,
        symbol: str,
        exchange: str,
        order_type: str,
        price: float,
        product_type: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm Order")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        # Prevent accidental dismiss by clicking outside
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(320)
        self.setMaximumWidth(400)

        self._side = side.upper()
        is_buy = self._side == "BUY"
        accent = "#3fb950" if is_buy else "#f85149"

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title = QLabel("Confirm Order")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #e6edf3;")
        layout.addWidget(title)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #30363d;")
        layout.addWidget(sep)

        # Summary block
        summary = QWidget()
        summary.setStyleSheet(
            f"background: #161b22; border: 1px solid #30363d; border-radius: 4px;"
        )
        sum_layout = QVBoxLayout(summary)
        sum_layout.setSpacing(6)
        sum_layout.setContentsMargins(16, 12, 16, 12)

        # Side + quantity + symbol
        side_line = QLabel(
            f'<span style="color:{accent}; font-weight:bold; font-size:15px;">'
            f"{self._side}</span>"
            f'<span style="color:#e6edf3; font-size:15px;"> {quantity} {symbol}</span>'
            f'<span style="color:#8b949e; font-size:13px;"> {exchange}</span>'
        )
        side_line.setTextFormat(Qt.TextFormat.RichText)
        sum_layout.addWidget(side_line)

        # Order type + price
        if order_type in ("MARKET", "STOPLOSS_MARKET"):
            price_text = f"{order_type} (market price)"
        else:
            price_text = f"{order_type} @ ₹{price:,.2f}"
        price_label = QLabel(price_text)
        price_label.setStyleSheet("color: #8b949e; font-size: 12px;")
        sum_layout.addWidget(price_label)

        # Product type
        prod_label = QLabel(f"Product: {product_type}")
        prod_label.setStyleSheet("color: #8b949e; font-size: 12px;")
        sum_layout.addWidget(prod_label)

        layout.addWidget(summary)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #30363d;")
        layout.addWidget(sep2)

        # Buttons
        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setSpacing(8)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(32)
        cancel_btn.setStyleSheet(
            "QPushButton { background: #21262d; color: #e6edf3;"
            " border: 1px solid #30363d; border-radius: 4px; }"
            "QPushButton:hover { background: #30363d; }"
        )
        cancel_btn.clicked.connect(self.reject)

        confirm_btn = QPushButton("Confirm")
        confirm_btn.setFixedHeight(32)
        confirm_btn.setStyleSheet(
            f"QPushButton {{ background: {accent}22; color: {accent};"
            f" border: 1px solid {accent}; border-radius: 4px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {accent}44; }}"
        )
        confirm_btn.clicked.connect(self.accept)
        confirm_btn.setDefault(True)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(confirm_btn)
        layout.addWidget(btn_row)
