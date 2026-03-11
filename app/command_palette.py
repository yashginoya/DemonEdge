"""Command Palette — Spotlight / VS Code-style widget launcher.

Open with Ctrl+K or the ⌘ Widgets button in the status bar.

Windows compatibility note
--------------------------
``WA_TranslucentBackground`` combined with ``FramelessWindowHint`` on Windows
causes ``Qt: UpdateLayeredWindowIndirect failed`` errors from the DWM compositor.
This palette therefore uses a fully opaque solid background.  Rounded corners
are achieved via ``border-radius`` on the inner ``QFrame``; since the window
background and the frame background are the same colour (#1a1a1a), the corners
are visually indistinguishable from a true transparent-corner effect on a dark
desktop.  ``QGraphicsDropShadowEffect`` is not used for the same reason.
Visual depth is communicated instead through a slightly lighter border (#3a3a3a).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.widget_registry import WidgetDefinition, WidgetRegistry

# Category → fallback emoji icon (used when WidgetDefinition.icon is empty)
_CATEGORY_ICONS: dict[str, str] = {
    "Market Data": "📈",
    "Orders": "📋",
    "System": "⚙",
}
_DEFAULT_ICON = "▪"

_PALETTE_W = 500
_ROW_H = 56
_MAX_VISIBLE_ROWS = 6


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _highlight(name: str, query: str) -> str:
    """Wrap the matched substring in a blue bold HTML span."""
    if not query:
        return name
    idx = name.lower().find(query.lower())
    if idx == -1:
        return name
    end = idx + len(query)
    return (
        name[:idx]
        + f'<span style="color:#58a6ff;font-weight:bold;">{name[idx:end]}</span>'
        + name[end:]
    )


def _fuzzy_score(name: str, query: str) -> int | None:
    """Return a match score (lower = better match) or None if no match.

    - Exact substring: score = position of match in name (0 = starts at beginning).
    - Fuzzy (all query chars appear in order): score = 1000 + last matched position.
    - No match: None.
    """
    if not query:
        return 0
    n = name.lower()
    q = query.lower()

    idx = n.find(q)
    if idx != -1:
        return idx

    pos = 0
    last = -1
    for ch in q:
        found = n.find(ch, pos)
        if found == -1:
            return None
        last = found
        pos = found + 1
    return 1000 + last


# ---------------------------------------------------------------------------
# Row widget
# ---------------------------------------------------------------------------


class _ResultRow(QWidget):
    """One result row inside the palette list."""

    def __init__(self, defn: WidgetDefinition, query: str) -> None:
        super().__init__()
        self.setFixedHeight(_ROW_H)
        # No WA_TranslucentBackground — causes UpdateLayeredWindowIndirect errors
        # on Windows.  Transparent stylesheet background lets the QListWidget
        # item delegate paint the selection/hover colour behind this widget.
        self.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        # Icon chip
        icon_char = defn.icon or _CATEGORY_ICONS.get(defn.category, _DEFAULT_ICON)
        icon_lbl = QLabel(icon_char)
        icon_lbl.setFixedSize(36, 36)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(
            "font-size: 18px;"
            " background: #252525;"
            " border-radius: 6px;"
            " color: #c9d1d9;"
        )
        layout.addWidget(icon_lbl)

        # Name + description column
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        name_lbl = QLabel(_highlight(defn.display_name, query))
        name_lbl.setTextFormat(Qt.TextFormat.RichText)
        name_lbl.setStyleSheet(
            "font-size: 13px; color: #e6edf3; background: transparent;"
        )

        desc_text = defn.description or defn.category
        desc_lbl = QLabel(desc_text)
        desc_lbl.setStyleSheet(
            "font-size: 11px; color: #888888; background: transparent;"
        )

        text_col.addWidget(name_lbl)
        text_col.addWidget(desc_lbl)
        layout.addLayout(text_col, 1)


# ---------------------------------------------------------------------------
# Palette window
# ---------------------------------------------------------------------------

_PANEL_QSS = (
    "QFrame#CmdPanel {"
    "  background: #1a1a1a;"
    "  border: 1px solid #3a3a3a;"
    "  border-radius: 10px;"
    "}"
)

_SEARCH_QSS = (
    "QLineEdit {"
    "  background: transparent;"
    "  border: none;"
    "  border-bottom: 1px solid #2d2d2d;"
    "  color: #e6edf3;"
    "  font-size: 14px;"
    "  padding: 12px 16px;"
    "}"
    "QLineEdit::placeholder {"
    "  color: #484f58;"
    "}"
)

_LIST_QSS = (
    "QListWidget {"
    "  background: transparent;"
    "  border: none;"
    "  outline: none;"
    "  color: #e6edf3;"
    "  padding: 4px 4px;"
    "}"
    "QListWidget::item {"
    "  border: none;"
    "  border-radius: 4px;"
    "  padding: 0;"
    "}"
    "QListWidget::item:selected, QListWidget::item:hover {"
    "  background: #1f3050;"
    "  border-radius: 4px;"
    "}"
)


class CommandPalette(QWidget):
    """Frameless floating command palette.

    Emits ``widget_selected(widget_id)`` when the user picks a widget.
    Dismisses on Escape, Enter/click to launch, or click-outside (window
    deactivate).

    Usage::

        self._palette = CommandPalette(main_window)
        self._palette.widget_selected.connect(self.spawn_widget)
        self._palette.show_centered_on(self)
    """

    widget_selected = Signal(str)  # emits widget_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint,
        )
        # NOTE: WA_TranslucentBackground intentionally omitted — causes
        # Qt: UpdateLayeredWindowIndirect failed errors on Windows.
        # Solid opaque background is used instead; see module docstring.
        self.setFixedWidth(_PALETTE_W)
        # Window background matches the panel so the corners (outside
        # border-radius curve) are visually invisible on a dark desktop.
        self.setStyleSheet("CommandPalette { background: #1a1a1a; }")
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Rounded dark panel — fills the window exactly.
        # border-radius here clips child content; the window-level corners
        # (#1a1a1a) match the panel background so they're invisible.
        self._panel = QFrame()
        self._panel.setObjectName("CmdPanel")
        self._panel.setStyleSheet(_PANEL_QSS)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # ---- Search field ----
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search widgets…")
        self._search.setStyleSheet(_SEARCH_QSS)
        self._search.textChanged.connect(self._refresh)
        self._search.installEventFilter(self)
        panel_layout.addWidget(self._search)

        # ---- Results list ----
        self._list = QListWidget()
        self._list.setStyleSheet(_LIST_QSS)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._list.setSpacing(0)
        self._list.itemActivated.connect(self._emit_selected)
        self._list.installEventFilter(self)
        panel_layout.addWidget(self._list)

        # ---- No-results label ----
        self._no_results = QLabel("No widgets found")
        self._no_results.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_results.setStyleSheet(
            "color: #484f58; font-size: 13px; padding: 20px; background: transparent;"
        )
        self._no_results.hide()
        panel_layout.addWidget(self._no_results)

        outer.addWidget(self._panel)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_centered_on(self, anchor: QWidget) -> None:
        """Reset content, position VS Code-style (top-third), and show."""
        self._search.clear()
        self._refresh("")

        geo = anchor.geometry()
        x = geo.center().x() - _PALETTE_W // 2
        # Position ~1/5 from the top of the main window — VS Code-style
        y = geo.y() + geo.height() // 5
        self.move(x, y)

        self.show()
        self.raise_()
        self.activateWindow()
        self._search.setFocus()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh(self, query: str = "") -> None:
        """Rebuild results list from registry, filtered + scored by query."""
        self._list.clear()

        scored: list[tuple[int, WidgetDefinition]] = []
        for defn in WidgetRegistry.get_all():
            score = _fuzzy_score(defn.display_name, query)
            if score is not None:
                scored.append((score, defn))

        scored.sort(key=lambda x: (x[0], x[1].display_name.lower()))

        for _, defn in scored:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, defn.widget_id)
            row = _ResultRow(defn, query)
            item.setSizeHint(QSize(_PALETTE_W - 8, _ROW_H))
            self._list.addItem(item)
            self._list.setItemWidget(item, row)

        has_results = self._list.count() > 0
        if has_results:
            self._list.setCurrentRow(0)

        visible = min(self._list.count(), _MAX_VISIBLE_ROWS)
        self._list.setFixedHeight(visible * _ROW_H + 8 if has_results else 0)
        self._list.setVisible(has_results)
        self._no_results.setVisible(not has_results)
        self.adjustSize()

    def _emit_selected(self, item: QListWidgetItem) -> None:
        widget_id: str = item.data(Qt.ItemDataRole.UserRole)
        if widget_id:
            self.widget_selected.emit(widget_id)
            self.hide()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.WindowDeactivate:
            self.hide()
        super().changeEvent(event)

    def eventFilter(self, obj: object, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()  # type: ignore[attr-defined]
            if key == Qt.Key.Key_Escape:
                self.hide()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self._list.currentItem()
                if item:
                    self._emit_selected(item)
                return True
            if key == Qt.Key.Key_Down:
                r = self._list.currentRow()
                if r < self._list.count() - 1:
                    self._list.setCurrentRow(r + 1)
                return True
            if key == Qt.Key.Key_Up:
                r = self._list.currentRow()
                if r > 0:
                    self._list.setCurrentRow(r - 1)
                return True
        return super().eventFilter(obj, event)
