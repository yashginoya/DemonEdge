from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from widgets.base_widget import BaseWidget


class PositionsWidget(BaseWidget):
    """Positions & P&L — placeholder until Phase 5."""

    widget_id = "positions"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Positions & P&L", parent)
        self.setMinimumHeight(120)

        content = QWidget()
        layout = QVBoxLayout(content)
        label = QLabel("Positions & P&L\n\ncoming in Phase 5")
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
        widget_id=PositionsWidget.widget_id,
        display_name="Positions & P&L",
        category="Orders",
        factory=PositionsWidget,
    )
)
