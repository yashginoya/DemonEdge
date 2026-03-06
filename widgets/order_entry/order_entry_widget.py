from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from widgets.base_widget import BaseWidget


class OrderEntryWidget(BaseWidget):
    """Order entry form — placeholder until Phase 5."""

    widget_id = "order_entry"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Order Entry", parent)
        self.setMinimumWidth(220)

        content = QWidget()
        layout = QVBoxLayout(content)
        label = QLabel("Order Entry\n\ncoming in Phase 5")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #484f58; font-size: 14px;")
        layout.addWidget(label)
        self.setWidget(content)

    def on_show(self) -> None:
        pass

    def on_hide(self) -> None:
        pass

    def save_state(self) -> dict:
        return {}

    def restore_state(self, state: dict) -> None:
        pass


# Self-register at import time
from app.widget_registry import WidgetDefinition, WidgetRegistry  # noqa: E402

WidgetRegistry.register(
    WidgetDefinition(
        widget_id=OrderEntryWidget.widget_id,
        display_name="Order Entry",
        category="Orders",
        factory=OrderEntryWidget,
    )
)
