"""Custom-drawn pieces of the UI."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QLabel, QLayout, QSizePolicy, QStyle, QStyledItemDelegate, QWidget

from . import theme

NAME_ROLE = Qt.ItemDataRole.UserRole + 1
SUMMARY_ROLE = Qt.ItemDataRole.UserRole + 2
BADGE_ROLE = Qt.ItemDataRole.UserRole + 3
KIND_ROLE = Qt.ItemDataRole.UserRole + 4


def wrap_words(text: str, fm: QFontMetrics, width: int, sep: str = " ") -> list[str]:
    """Greedy line wrap at `sep` (a word that alone is too wide is split by characters). Never drops text."""
    width = max(width, fm.horizontalAdvance("W"))
    lines: list[str] = []
    for word in [w for w in text.split(sep) if w] or [""]:
        while fm.horizontalAdvance(word) > width:  # one very long word: break it
            n = len(word)
            while n > 1 and fm.horizontalAdvance(word[:n]) > width:
                n -= 1
            if lines and lines[-1] == "":
                lines.pop()
            lines.append(word[:n])
            word = word[n:]
        if lines and fm.horizontalAdvance(lines[-1] + sep + word) <= width and lines[-1]:
            lines[-1] += sep + word
        else:
            lines.append(word)
    return lines


class InstanceDelegate(QStyledItemDelegate):
    """Sidebar row: instance name, muted version/loader/launcher line, optional 'N ready' pill.

    Nothing is cut off: when the sidebar is narrow, the name wraps between words and the details wrap
    between their parts ("1.21.11 · Fabric" / "MultiMC"), and the row grows taller."""

    PAD_X, PAD_Y = 24, 9  # 14 left + 10 right inside the row; 9 above and below the text

    def _fonts(self, base: QFont) -> tuple[QFont, QFont, QFont]:
        name = QFont(base)
        name.setPixelSize(theme.emphasis_px("base", 1.05))
        name.setWeight(theme.weight("demibold"))
        sub = QFont(base)
        sub.setPixelSize(theme.px("small"))
        badge = QFont(base)
        badge.setPixelSize(theme.px("caption"))
        badge.setWeight(theme.weight("bold"))
        return theme.crisp(name), theme.crisp(sub), theme.crisp(badge)

    @staticmethod
    def _badge_label(index) -> str:
        count = index.data(BADGE_ROLE) or 0
        return f"{count} ready" if count else ""

    def layout(self, index, row_width: int, base: QFont) -> tuple[list[str], list[str], int]:
        """(name lines, detail lines, row height) for a row this wide."""
        name_f, sub_f, badge_f = self._fonts(base)
        text_w = row_width - 2 - self.PAD_X
        badge = self._badge_label(index)
        badge_w = QFontMetrics(badge_f).horizontalAdvance(badge) + 22 if badge else 0
        name_lines = wrap_words(index.data(NAME_ROLE) or "", QFontMetrics(name_f), text_w - badge_w)
        parts = [p for p in (index.data(SUMMARY_ROLE) or "").split(" · ") if p]
        if index.data(KIND_ROLE):  # "Prism" or "MultiMC" for linked instances
            parts.append(index.data(KIND_ROLE))
        sub_lines = wrap_words(" · ".join(parts), QFontMetrics(sub_f), text_w, sep=" · ")
        height = (len(name_lines) * QFontMetrics(name_f).height() + 2
                  + len(sub_lines) * QFontMetrics(sub_f).height() + 2 * self.PAD_Y + 4)
        return name_lines, sub_lines, height

    def _row_width(self, option) -> int:
        view = self.parent()
        if view is not None and hasattr(view, "viewport"):
            return view.viewport().width()
        return option.rect.width()

    def sizeHint(self, option, index) -> QSize:
        width = self._row_width(option)
        return QSize(width, self.layout(index, width, option.font)[2])

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect.adjusted(0, 2, -2, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setPen(Qt.PenStyle.NoPen)
        if selected or hover:
            painter.setBrush(QColor(theme.color("selected" if selected else "hover")))
            painter.drawRoundedRect(QRectF(r), 8, 8)
        if selected:
            painter.setBrush(QColor(theme.color("accent")))
            painter.drawRoundedRect(QRectF(r.left(), r.top() + 9, 3, r.height() - 18), 1.5, 1.5)

        name_f, sub_f, badge_f = self._fonts(option.font)
        name_lines, sub_lines, _ = self.layout(index, option.rect.width(), option.font)
        text = r.adjusted(14, self.PAD_Y, -10, -self.PAD_Y)
        name_h, sub_h = QFontMetrics(name_f).height(), QFontMetrics(sub_f).height()

        badge = self._badge_label(index)
        if badge:
            bm = QFontMetrics(badge_f)
            badge_w = bm.horizontalAdvance(badge) + 14
            pill = QRect(text.right() - badge_w, text.top() + (name_h - bm.height() - 4) // 2, badge_w, bm.height() + 4)
            painter.setBrush(QColor(theme.color("accent")))
            painter.drawRoundedRect(QRectF(pill), pill.height() / 2, pill.height() / 2)
            painter.setFont(badge_f)
            painter.setPen(QColor(theme.color("on_accent")))
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, badge)

        y = text.top()
        painter.setFont(name_f)
        painter.setPen(QColor(theme.color("text")))
        for line in name_lines:
            painter.drawText(QRect(text.left(), y, text.width(), name_h),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
            y += name_h
        y += 2
        painter.setFont(sub_f)
        painter.setPen(QColor(theme.color("muted")))
        for line in sub_lines:
            painter.drawText(QRect(text.left(), y, text.width(), sub_h),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
            y += sub_h
        painter.restore()


class FlowLayout(QLayout):
    """Lays out widgets left to right and wraps them onto new lines (for the category chips)."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, dry=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _layout(self, rect, dry):
        x, y, line_h = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() and line_h:
                x, y, line_h = rect.x(), y + line_h + self._spacing, 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


def flow_row(*widgets, spacing: int = 6) -> QWidget:
    """A row of widgets that wraps onto the next line when the window is narrow."""
    row = QWidget()
    lay = FlowLayout(row, spacing)
    for wdg in widgets:
        lay.addWidget(wdg)
    return row


class ElidedLabel(QLabel):
    """A one-line label that shortens itself with "…" instead of forcing the window wider.
    The full text is in the tooltip."""

    def __init__(self, text: str = "", mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle):
        super().__init__()
        self._full, self._mode = "", mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._refresh()

    def fullText(self) -> str:
        return self._full

    def minimumSizeHint(self) -> QSize:
        return QSize(40, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._refresh()

    def _refresh(self) -> None:
        QLabel.setText(self, self.fontMetrics().elidedText(self._full, self._mode, max(0, self.width())))
