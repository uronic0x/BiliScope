"""PySide6 user interface. Falls back to biliscope.ui (Tkinter) if Qt is unavailable."""
from __future__ import annotations
import json
import logging
import queue
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QEvent, QObject, QPointF, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QAbstractItemView, QSizePolicy, QAbstractScrollArea, QAbstractSpinBox, QApplication,
    QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
from .config import Settings
from .credentials import load_key, save_key
from .domain import AppError, comment_payload, timestamp
from .i18n import tr
from .runtime import ROOT, RUNTIME, inside, atomic_json, path_report, redact, remember_secret
from .service import Service
from .auto import AutoPlan
from .prompts import PRESETS, CORE, preset_text

log = logging.getLogger('biliscope')

# ---------------------------------------------------------------------------
# Small raster icons. Qt style sheets cannot draw a check mark or a caret, and
# the default Windows artwork is clipped by custom padding, so the few glyphs
# needed here are painted once into the project cache directory.
# ---------------------------------------------------------------------------

def _paint_icon(path: Path, size: tuple[int, int], draw) -> str:
    path = Path(path)
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            pixmap = QPixmap(*size)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            draw(painter)
            painter.end()
            pixmap.save(str(path))
    except Exception:  # A missing icon must never prevent the UI from starting.
        log.warning('Could not prepare UI icon %s', path.name)
        return ''
    return path.as_posix()


def _draw_check(painter: QPainter):
    """White tick drawn at its final 16 px size; scaling would blur the stroke."""
    painter.setPen(QPen(QColor('#ffffff'), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    painter.drawPolyline(QPolygonF([QPointF(3.2, 8.2), QPointF(6.6, 11.6), QPointF(12.6, 4.6)]))


def _draw_chevron(painter: QPainter):
    painter.setPen(QPen(QColor('#5b6675'), 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    painter.drawPolyline(QPolygonF([QPointF(2.6, 4.4), QPointF(6.0, 7.8), QPointF(9.4, 4.4)]))


def _draw_triangle(painter: QPainter, up: bool):
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor('#5b6675'))
    if up:
        painter.drawPolygon(QPolygonF([QPointF(0.6, 4.4), QPointF(8.4, 4.4), QPointF(4.5, 0.6)]))
    else:
        painter.drawPolygon(QPolygonF([QPointF(0.6, 0.6), QPointF(8.4, 0.6), QPointF(4.5, 4.4)]))


def _icons() -> dict[str, str]:
    try:
        folder = inside(RUNTIME / 'cache' / 'ui')
    except Exception:
        return {'check': '', 'chevron': '', 'up': '', 'down': ''}
    return {
        'check': _paint_icon(folder / 'check-16.png', (16, 16), _draw_check),
        'chevron': _paint_icon(folder / 'chevron-12.png', (12, 12), _draw_chevron),
        'up': _paint_icon(folder / 'arrow-up-9x5.png', (9, 5), lambda p: _draw_triangle(p, True)),
        'down': _paint_icon(folder / 'arrow-down-9x5.png', (9, 5), lambda p: _draw_triangle(p, False)),
    }


QSS_TEMPLATE = """
* { font-family: 'Segoe UI', 'Microsoft YaHei UI', 'Microsoft YaHei', sans-serif; font-size: 13px; color: #212529; }
QMainWindow, QDialog, QMessageBox { background: #f6f7f9; }
QWidget#page { background: #ffffff; }
QWidget#surface { background: #ffffff; }
QLabel { background: transparent; }
QLabel#title { font-size: 21px; font-weight: 700; color: #14213d; }
QLabel#subtitle { color: #8a94a6; }
QLabel#section { font-size: 13px; font-weight: 700; color: #0f6d78; }
QLabel#hint { color: #8a94a6; }
QLabel#status { color: #6b7684; border-top: 1px solid #eef1f4; padding: 7px 2px 0 2px; }
QFrame#rule { background: #eef1f4; border: none; max-height: 1px; min-height: 1px; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: #ffffff; border: 1px solid #dfe4ea; border-radius: 6px;
    padding: 6px 9px; selection-background-color: #bfe3e7; selection-color: #14213d; }
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #c9d2db; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #0f8b98; }
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
    background: #f5f6f8; color: #9aa3ad; border-color: #eceff3; }
QComboBox { padding-right: 28px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right;
    width: 24px; border: none; background: transparent; }
QComboBox::down-arrow { image: url(@CHEVRON@); width: 12px; height: 12px; }
QComboBox::down-arrow:disabled { image: none; }
QComboBox QAbstractItemView { background: #ffffff; border: 1px solid #dfe4ea; border-radius: 8px;
    padding: 4px; outline: 0; selection-background-color: #e6f4f5; selection-color: #14213d; }
QSpinBox { padding: 5px 26px 5px 9px; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 22px;
    height: 15px; border: none; border-left: 1px solid #eef1f4; border-top-right-radius: 6px;
    background: #f8f9fa; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 22px;
    height: 15px; border: none; border-left: 1px solid #eef1f4; border-bottom-right-radius: 6px;
    background: #f8f9fa; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #eef2f5; }
QSpinBox::up-arrow { image: url(@UP@); width: 9px; height: 5px; }
QSpinBox::down-arrow { image: url(@DOWN@); width: 9px; height: 5px; }
QPushButton {
    background: #f2f4f7; border: 1px solid #dfe4ea; border-radius: 6px;
    padding: 7px 16px; min-height: 18px; color: #333d4b; }
QPushButton:hover { background: #e9edf2; }
QPushButton:pressed { background: #dfe4ea; }
QPushButton:focus { border: 1px solid #0f8b98; }
QPushButton:disabled { background: #f7f8fa; border-color: #eef1f4; color: #aab2bc; }
QPushButton#accent { background: #0f7d88; border: 1px solid #0f7d88; color: #ffffff; font-weight: 600; }
QPushButton#accent:hover { background: #0b6d77; border-color: #0b6d77; }
QPushButton#accent:pressed { background: #095c65; border-color: #095c65; }
QPushButton#accent:disabled { background: #b9d7da; border-color: #b9d7da; color: #f2fbfb; }
QPushButton#quiet { background: transparent; border: 1px solid transparent; color: #0f7d88; padding: 5px 9px; }
QPushButton#quiet:hover { background: #eef7f8; }
QPushButton#quiet:disabled { color: #b6bec8; background: transparent; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #b6bec6;
    border-radius: 4px; background: #ffffff; }
QCheckBox::indicator:hover { border-color: #0f8b98; }
QCheckBox::indicator:checked { background: #0f7d88; border-color: #0f7d88; image: url(@CHECK@); }
QCheckBox:disabled { color: #9aa3ad; }
QCheckBox::indicator:disabled { border-color: #e3e7ec; background: #f5f6f8; }
QTabWidget::pane { border: none; background: #ffffff; }
QTabWidget::tab-bar { left: 0; }
QTabBar::tab { background: transparent; padding: 8px 16px; margin-right: 4px;
    color: #7b8698; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #0f7d88; font-weight: 600; border-bottom: 2px solid #0f7d88; }
QTabBar::tab:hover:!selected { color: #3c4858; }
QTabBar::tab:disabled { color: #c2c8d2; }
QTabBar::scroller { width: 26px; }
QTreeWidget { background: #ffffff; border: 1px solid #e8ecf0; border-radius: 8px;
    alternate-background-color: #fafbfc; selection-background-color: #d9eef1;
    selection-color: #14213d; outline: 0; }
QTreeWidget::item { height: 28px; border: none; }
QTreeWidget::item:selected { background: #d9eef1; color: #14213d; }
QTreeWidget::item:selected:!active { background: #eaf5f6; color: #14213d; }
QTreeWidget::item:hover:!selected { background: #f4f8f9; }
QHeaderView { background: transparent; }
QHeaderView::section { background: #f5f7f9; color: #5b6675; border: none;
    border-bottom: 1px solid #e8ecf0; padding: 6px 10px; font-weight: 600; }
QHeaderView::section:first { border-top-left-radius: 8px; }
QHeaderView::section:last { border-top-right-radius: 8px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px 2px 2px 0; }
QScrollBar::handle:vertical { background: #cfd6de; border-radius: 4px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #b7c0ca; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0 2px 2px 2px; }
QScrollBar::handle:horizontal { background: #cfd6de; border-radius: 4px; min-width: 28px; }
QScrollBar::handle:horizontal:hover { background: #b7c0ca; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; background: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QSplitter::handle { background: #eef1f4; }
QSplitter::handle:vertical { height: 6px; }
QSplitter::handle:hover { background: #cfe7ea; }
QToolTip { background: #ffffff; color: #212529; border: 1px solid #dfe4ea; padding: 5px 7px; }
"""


def build_qss(icons: dict[str, str]) -> str:
    return (QSS_TEMPLATE.replace('@CHECK@', icons.get('check', ''))
            .replace('@CHEVRON@', icons.get('chevron', ''))
            .replace('@UP@', icons.get('up', ''))
            .replace('@DOWN@', icons.get('down', '')))


class EmptyState(QLabel):
    """Centred hint drawn over an empty table.

    A placeholder *row* cannot be used: a table with a single column-spanned
    row mis-lays the header and paints a stray cell outline. A label on top of
    the viewport avoids touching the table model at all.
    """

    def __init__(self, tree: QTreeWidget):
        super().__init__(tree.viewport())
        self.setObjectName('empty')
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        tree.viewport().installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self.setGeometry(self.parentWidget().rect())
        return False

    def show_text(self, text: str):
        self.setText(text)
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()


class WheelGuard(QObject):
    """Keep the mouse wheel scrolling the page instead of editing values.

    Combo boxes and spin boxes follow the Windows convention of changing their
    value on wheel hover. That is the wrong default inside a long form: a small
    scroll past a row silently rewrites a setting. While the control does not
    have keyboard focus, the wheel is forwarded to the surrounding scroll area;
    once the user clicks into the control, the wheel keeps its native meaning.
    """

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and isinstance(obj, (QComboBox, QAbstractSpinBox)):
            if not obj.hasFocus():
                area = obj.parentWidget()
                while area is not None and not isinstance(area, QAbstractScrollArea):
                    area = area.parentWidget()
                if area is not None:
                    QApplication.sendEvent(area.viewport(), event)
                    return True
        return False


class FormGrid:
    """Two-column form: right-aligned labels, bounded fields, sane spacing."""

    def __init__(self, parent: QWidget, label_width: int = 176):
        self.grid = QGridLayout(parent)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(9)
        self.grid.setColumnMinimumWidth(0, label_width)
        self.grid.setColumnStretch(0, 0)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(2, 0)
        self.row = 0

    def heading(self, label: QWidget) -> QWidget:
        self.grid.addWidget(label, self.row, 0, 1, 3)
        self.row += 1
        return label

    def rule(self):
        line = QFrame()
        line.setObjectName('rule')
        line.setFrameShape(QFrame.HLine)
        self.grid.addWidget(line, self.row, 0, 1, 3)
        self.row += 1

    def full(self, widget: QWidget):
        self.grid.addWidget(widget, self.row, 0, 1, 3)
        self.row += 1

    def add(self, label: QWidget | None, field: QWidget, span: int = 1):
        if label is not None:
            self.grid.addWidget(label, self.row, 0, Qt.AlignRight | Qt.AlignVCenter)
        if isinstance(field, (QLineEdit, QComboBox, QSpinBox)):
            field.setFixedHeight(34)  # QSpinBox otherwise resolves 2 px taller
        self.grid.addWidget(field, self.row, 1, 1, span)
        self.row += 1


def _scrollable(body: QWidget, margins=(24, 18, 24, 18)) -> QScrollArea:
    layout = body.layout()
    if layout is not None:
        layout.setContentsMargins(*margins)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(body)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return area


def _fixed(widget: QWidget, width: int, height: int | None = None) -> QWidget:
    widget.setFixedWidth(width)
    if height is not None:
        widget.setFixedHeight(height)
    return widget


def _bounded(widget: QWidget, width: int) -> QWidget:
    """Prefer `width` but shrink instead of forcing a horizontal scroll bar."""
    widget.setMaximumWidth(width)
    widget.setMinimumWidth(min(width, widget.minimumSizeHint().width()))
    widget.setSizePolicy(QSizePolicy.Expanding, widget.sizePolicy().verticalPolicy())
    return widget


class App:
    def __init__(self):
        self.app = QApplication.instance() or QApplication([])
        self.app.setStyle('Fusion')
        self.app.setStyleSheet(build_qss(_icons()))
        self.wheel_guard = WheelGuard(self.app)
        self.app.installEventFilter(self.wheel_guard)
        self.win = QMainWindow()
        self._size_window()
        self.queue = queue.Queue()
        self.future = None
        self.closing = False
        self.text_bindings = []
        self.mentions = []
        self.reply = None
        self.auto_running = False
        self.display_evidence = None
        self._comments = []
        self._auto_records = []
        try:
            self.auto_plan = AutoPlan.load()
        except Exception:
            self.auto_plan = AutoPlan()
        try:
            self.settings = Settings.load()
        except Exception:
            self.settings = Settings(); log.warning('Invalid settings; using defaults')
        self.lang = self.settings.language
        self.prompt_preset = self.settings.prompt_preset
        try:
            key = load_key()
        except Exception:
            key = ''; log.warning('Saved key could not be decrypted')
        remember_secret(key)
        self.key_value = key

        central = QWidget(); central.setObjectName('page')
        root = QVBoxLayout(central); root.setContentsMargins(24, 18, 24, 10); root.setSpacing(6)
        header = QHBoxLayout()
        self.title_label = self.label('app_title', objectName='title')
        header.addWidget(self.title_label)
        header.addStretch(1)
        self.lang_combo = QComboBox(); self.lang_combo.addItems(['CN', 'EN'])
        self.lang_combo.setCurrentText(self.lang.upper())
        _fixed(self.lang_combo, 86)
        self.lang_combo.currentTextChanged.connect(self.change_language)
        header.addWidget(self.lang_combo)
        root.addLayout(header)
        root.addWidget(self.label('tagline', objectName='subtitle'))

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        root.addWidget(self.tabs, 1)
        self.pages = {}
        for k in ('video_tab', 'comment_tab', 'auto_tab', 'prompts_tab', 'settings_tab', 'diagnostics_tab'):
            page = QWidget(); page.setObjectName('page')
            self.pages[k] = page
            self.tabs.addTab(page, self.t(k))
        self.build_video(); self.build_comment(); self.build_auto()
        self.build_settings(); self.build_prompts(); self.build_diagnostics()

        self.status = QLabel(self.t('ready')); self.status.setObjectName('status')
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(26)
        root.addWidget(self.status)
        self.win.setCentralWidget(central)

        self.service = Service(self.queue.put)
        self.win.closeEvent = self.close_event
        self.timer = QTimer(self.win); self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll); self.timer.start()
        self.translate()

    # ----- window -----
    def _size_window(self):
        width, height = 1180, 880
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = max(940, min(width, int(available.width() * 0.92)))
            height = max(660, min(height, int(available.height() * 0.9)))
            self.win.setMinimumSize(min(900, width), min(620, height))
            geometry = self.win.frameGeometry()
            geometry.moveCenter(available.center())
            self.win.move(geometry.topLeft())
        else:
            self.win.setMinimumSize(900, 620)
        self.win.resize(width, height)

    # ----- helpers -----
    def t(self, key): return tr(key, self.lang)

    def label(self, key, objectName=None, wrap=False):
        w = QLabel(self.t(key))
        if objectName: w.setObjectName(objectName)
        if wrap: w.setWordWrap(True)
        self.text_bindings.append((w, key))
        return w

    def button(self, key, command, accent=False):
        w = QPushButton(self.t(key))
        if accent: w.setObjectName('accent')
        w.setCursor(Qt.PointingHandCursor)
        w.clicked.connect(command)
        self.text_bindings.append((w, key))
        return w

    def quiet_button(self, key, command):
        w = self.button(key, command)
        w.setObjectName('quiet')
        return w

    def check(self, key, checked):
        w = QCheckBox(self.t(key)); w.setChecked(checked)
        w.setCursor(Qt.PointingHandCursor)
        self.text_bindings.append((w, key))
        return w

    def set_status(self, text): self.status.setText(text)

    @staticmethod
    def set_text(widget, text):
        widget.setPlainText(text)

    def info(self, text): QMessageBox.information(self.win, self.t('info'), text)

    def _table(self, columns: int, min_rows: int = 3) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setColumnCount(columns)
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        tree.setSelectionMode(QAbstractItemView.SingleSelection)
        tree.setDragDropMode(QAbstractItemView.NoDragDrop)
        tree.setSortingEnabled(False)
        tree.setWordWrap(False)
        tree.setTextElideMode(Qt.ElideRight)
        tree.setAllColumnsShowFocus(False)
        tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        tree.header().setHighlightSections(False)
        tree.header().setSectionsMovable(False)
        tree.header().setStretchLastSection(True)
        tree.setMinimumHeight(tree.fontMetrics().height() + 30 + 28 * min_rows)
        tree.empty_state = EmptyState(tree)
        tree.empty_state.setStyleSheet('color: #98a2ad; font-size: 13px; background: transparent;')
        return tree

    def _placeholder(self, tree: QTreeWidget, text: str):
        state = getattr(tree, 'empty_state', None)
        if state is not None:
            state.show_text(text)
        else:
            tree.setAccessibleName(text)

    def _filled(self, tree: QTreeWidget):
        state = getattr(tree, 'empty_state', None)
        if state is not None:
            state.hide()

    def _source_label(self, source) -> str:
        key = {'initial': 'source_initial', 'extra-request': 'source_extra'}.get(str(source))
        if key:
            return self.t(key)
        return str(source or self.t('source_other'))

    def _auto_status(self, status) -> str:
        key = 'auto_state_' + str(status)
        text = self.t(key)
        return str(status) if text == key else text

    def _auto_detail(self, record) -> str:
        """Status plus the facts the outcome table used to drop."""
        status = record.get('status', '')
        parts = [self._auto_status(status)]
        if record.get('mention_only') and record.get('owner_mentioned'):
            parts = [self.t('auto_mention_only_label')]
        if record.get('owner_mentioned'):
            name = record.get('owner_name') or record.get('owner_uid') or ''
            confirmed = record.get('mentions_confirmed')
            mark = self.t('auto_mentioned') if confirmed else self.t('auto_mention_unconfirmed')
            parts.append(mark.format(name=name))
        elif record.get('mention_skipped') and status != 'mention_skipped':
            # "mention_skipped" already names the reason in its own status text.
            parts.append(self.t('auto_mention_skipped_' + str(record['mention_skipped']))
                         if self.t('auto_mention_skipped_' + str(record['mention_skipped'])) !=
                         'auto_mention_skipped_' + str(record['mention_skipped'])
                         else self.t('auto_mention_skipped').format(
                             reason=self._auto_status(record['mention_skipped'])))
        if isinstance(record.get('score'), int):
            parts.append(self.t('auto_score').format(score=record['score']))
        if record.get('error'):
            parts.append(str(record['error']))
        return ' · '.join(x for x in parts if x)

    # ----- video tab -----
    def build_video(self):
        p = self.pages['video_tab']
        v = QVBoxLayout(p); v.setContentsMargins(24, 18, 24, 16); v.setSpacing(7)
        v.addWidget(self.label('target'))
        self.target_edit = QLineEdit(self.settings_target_default())
        self.target_edit.setPlaceholderText('https://www.bilibili.com/video/BV…')
        self.target_edit.setClearButtonEnabled(True)
        v.addWidget(self.target_edit)
        v.addWidget(self.label('question'))
        self.question = QPlainTextEdit(self.t('default_question'))
        self.question.setFixedHeight(58)
        v.addWidget(self.question)
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(self.button('login', lambda: self.task(self.service.browser.login(), self.login_done)))
        row.addWidget(self.button('analyze', self.analyze, accent=True))
        row.addWidget(self.button('cancel', self.cancel))
        row.addStretch(1)
        row.addWidget(self.button('export', self.export))
        v.addLayout(row)
        v.addWidget(self.label('privacy_hint', objectName='hint', wrap=True))

        self.video_title = QLabel(''); self.video_title.setObjectName('section')
        self.video_title.setWordWrap(True)
        self.video_title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.video_title)
        self.video_meta = QLabel(''); self.video_meta.setObjectName('hint')
        self.video_meta.setWordWrap(True)
        v.addWidget(self.video_meta)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        self.result = QPlainTextEdit(); self.result.setReadOnly(True)
        self.result.setMinimumHeight(150)
        splitter.addWidget(self.result)
        lower = QWidget(); lv = QVBoxLayout(lower); lv.setContentsMargins(0, 8, 0, 0); lv.setSpacing(6)
        head = QHBoxLayout(); head.setSpacing(6)
        head.addWidget(self.label('evidence'))
        head.addStretch(1)
        self.view_frame_btn = self.quiet_button('view_frame', self.show_frame)
        self.view_frame_btn.setEnabled(False)
        head.addWidget(self.view_frame_btn)
        lv.addLayout(head)
        self.frames = self._table(3)
        self.frames.setMinimumHeight(self.frames.fontMetrics().height() + 30 + 28 * 3)
        self.frames.itemActivated.connect(self.show_frame)
        self.frames.itemSelectionChanged.connect(self._update_frame_actions)
        lv.addWidget(self.frames)
        lower.setMinimumHeight(self.frames.minimumHeight() + 44)
        splitter.addWidget(lower)
        splitter.setStretchFactor(0, 3); splitter.setStretchFactor(1, 2)
        splitter.setSizes([420, 210])
        v.addWidget(splitter, 1)

    def settings_target_default(self):
        return ''

    def _update_frame_actions(self):
        items = self.frames.selectedItems()
        enabled = bool(items) and items[0].data(0, Qt.UserRole) is not None
        self.view_frame_btn.setEnabled(bool(enabled and self.display_evidence))

    def _render_frames(self):
        frames = self.frames
        frames.clear()
        evidence = self.display_evidence
        rows = list(getattr(evidence, 'frames', ()) or ()) if evidence else []
        if not rows:
            self._placeholder(frames, self.t('evidence_empty'))
            self._update_frame_actions()
            return
        self._filled(frames)
        for index, frame in enumerate(rows):
            item = QTreeWidgetItem([timestamp(frame['actual_s']), timestamp(frame['requested_s']),
                                    self._source_label(frame.get('source', ''))])
            item.setData(0, Qt.UserRole, index)
            item.setToolTip(0, self.t('time'))
            item.setToolTip(2, str(frame.get('source', '')))
            frames.addTopLevelItem(item)
        metrics = frames.fontMetrics()
        width = max(metrics.horizontalAdvance('00:00'), metrics.horizontalAdvance(self.t('requested'))) + 34
        frames.header().setSectionResizeMode(0, QHeaderView.Fixed)
        frames.header().setSectionResizeMode(1, QHeaderView.Fixed)
        frames.header().resizeSection(0, max(110, width))
        frames.header().resizeSection(1, max(110, width))
        frames.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self._update_frame_actions()

    def _render_video_header(self):
        evidence = self.display_evidence
        if not evidence:
            self.video_title.setText('')
            self.video_meta.setText('')
            return
        self.video_title.setText(evidence.title)
        span = self.t('analysis_span').format(end=timestamp(evidence.scope_end), total=timestamp(evidence.duration))
        self.video_meta.setText('P' + str(evidence.part) + ' · ' + span)

    # ----- comment tab -----
    def build_comment(self):
        p = self.pages['comment_tab']
        v = QVBoxLayout(p); v.setContentsMargins(24, 18, 24, 16); v.setSpacing(8)
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(self.button('fetch_comments', self.fetch_comments))
        row.addWidget(self.button('reply_selected', self.select_reply))
        row.addWidget(self.button('new_comment', self.clear_reply))
        row.addStretch(1)
        v.addLayout(row)
        self.comment_tree = self._table(3)
        self.comment_tree.setMinimumHeight(self.comment_tree.fontMetrics().height() + 30 + 28 * 5)
        v.addWidget(self.comment_tree, 1)
        self.reply_label = QLabel(''); self.reply_label.setWordWrap(True)
        v.addWidget(self.reply_label)
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(self.label('mention_uid'))
        self.uid = QLineEdit(); self.uid.setFixedWidth(190)
        self.uid.setPlaceholderText('UID')
        row.addWidget(self.uid)
        row.addWidget(self.button('add_mention', self.add_mention))
        row.addWidget(self.button('clear_mentions', self.clear_mentions))
        row.addStretch(1)
        v.addLayout(row)
        self.mention_label = QLabel(''); self.mention_label.setWordWrap(True)
        v.addWidget(self.mention_label)
        v.addWidget(self.label('compose'))
        self.compose = QPlainTextEdit(); self.compose.setFixedHeight(124)
        v.addWidget(self.compose)
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(self.button('draft', self.draft))
        row.addStretch(1)
        row.addWidget(self.button('publish', self.publish, accent=True))
        v.addLayout(row)

    # ----- auto tab -----
    def build_auto(self):
        body = QWidget(); body.setObjectName('surface')
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(0); grid.setVerticalSpacing(0)
        form = FormGrid(body, label_width=196)
        form.grid.setContentsMargins(0, 0, 0, 0)
        grid.addLayout(form.grid, 0, 0)

        form.heading(self.label('group_run', objectName='section'))
        self.auto_enabled = QCheckBox(self.t('auto_enable'))
        self.auto_enabled.setCursor(Qt.PointingHandCursor)
        self.auto_enabled.toggled.connect(self.toggle_auto)
        self.text_bindings.append((self.auto_enabled, 'auto_enable'))
        form.full(self.auto_enabled)
        form.full(self.label('auto_hint', objectName='hint', wrap=True))
        form.rule()

        form.heading(self.label('group_source', objectName='section'))
        self.auto_widgets = {}
        w = QComboBox(); w.addItems(['recommendations', 'search', 'queue'])
        w.setCurrentText(self.auto_plan.source_mode)
        w.currentTextChanged.connect(self._sync_auto_source)
        self.auto_widgets['source_mode'] = w
        form.add(self.label('source_mode'), _bounded(w, 270))
        for key in ('keyword', 'start_time', 'owner_uid'):
            field = QLineEdit(getattr(self.auto_plan, key))
            field.setClearButtonEnabled(True)
            self.auto_widgets[key] = field
            form.add(self.label('auto_' + key), _bounded(field, 460))
        form.full(self.label('auto_queue_text'))
        self.auto_queue = QPlainTextEdit(self.auto_plan.queue_text)
        self.auto_queue.setFixedHeight(96)
        form.full(self.auto_queue)
        form.rule()

        form.heading(self.label('group_schedule', objectName='section'))
        for key, low, high in [('interval_minutes', 1, 1440), ('duration_minutes', 1, 1440),
                               ('max_videos', 1, 100), ('max_posts', 1, 100),
                               ('daily_post_limit', 1, 100), ('daily_analysis_limit', 1, 1000),
                               ('owner_every_minutes', 1, 1440), ('owner_daily_limit', 1, 100),
                               ('quality_threshold', 1, 10), ('max_analyze_failures', 1, 10),
                               ('analysis_backoff_minutes', 1, 1440)]:
            field = QSpinBox(); field.setRange(low, high); field.setValue(int(getattr(self.auto_plan, key)))
            field.setSuffix('')
            self.auto_widgets[key] = field
            form.add(self.label('auto_' + key), _bounded(field, 150))
        for key in ('publish_comments', 'mention_owner', 'mention_only', 'run_until_stopped',
                    'quality_gate', 'mention_requires_quality'):
            field = self.check('auto_' + key, bool(getattr(self.auto_plan, key)))
            field.toggled.connect(self._sync_auto_mention)
            self.auto_widgets[key] = field
            form.full(field)
        form.rule()

        form.heading(self.label('group_task', objectName='section'))
        for key in ('question', 'comment_instruction'):
            field = QLineEdit(getattr(self.auto_plan, key))
            field.setClearButtonEnabled(True)
            self.auto_widgets[key] = field
            form.add(self.label('auto_' + key), _bounded(field, 620))
        form.rule()

        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(self.button('auto_save', self.save_auto))
        row.addWidget(self.quiet_button('auto_show_requests', self.show_requests))
        row.addStretch(1)
        row.addWidget(self.button('cancel', self.cancel))
        form.full(self._layout_holder(row))

        form.heading(self.label('auto_results_title', objectName='section'))
        self.auto_results = self._table(2, min_rows=4)
        self.auto_results.setMinimumHeight(self.auto_results.fontMetrics().height() + 30 + 28 * 4)
        form.full(self.auto_results)

        page = self.pages['auto_tab']
        layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_scrollable(body))
        self._sync_auto_source()
        self._sync_auto_mention()

    def _sync_auto_source(self, *_):
        mode = self.auto_widgets['source_mode'].currentText()
        self.auto_widgets['keyword'].setEnabled(mode == 'search')
        self.auto_queue.setEnabled(mode == 'queue')

    def _sync_auto_mention(self, *_):
        wanted = self.auto_widgets['mention_owner'].isChecked()
        self.auto_widgets['owner_uid'].setEnabled(wanted)
        self.auto_widgets['owner_every_minutes'].setEnabled(wanted)
        self.auto_widgets['owner_daily_limit'].setEnabled(wanted)
        self.auto_widgets['mention_requires_quality'].setEnabled(wanted)
        self.auto_widgets['mention_only'].setEnabled(wanted)
        mention_only = wanted and self.auto_widgets['mention_only'].isChecked()
        # With "mention only" there is no comment body to write, so the comment
        # instruction and the quality-gated mention switch are irrelevant.
        quality = self.auto_widgets['quality_gate'].isChecked()
        self.auto_widgets['quality_threshold'].setEnabled(quality or wanted)
        self.auto_widgets['question'].setEnabled(True)
        if mention_only:
            self.auto_widgets['comment_instruction'].setEnabled(False)
        else:
            self.auto_widgets['comment_instruction'].setEnabled(True)
        # Always-on sessions have no session duration and no session video cap.
        always = self.auto_widgets['run_until_stopped'].isChecked()
        self.auto_widgets['duration_minutes'].setEnabled(not always)
        self.auto_widgets['max_videos'].setEnabled(not always)

    def _append_auto(self, record):
        self._auto_records.append(record)
        del self._auto_records[:-200]
        self._render_auto()

    def show_requests(self):
        """Show the exact prompt assembly of recent requests, read-only."""
        from .api_log import RequestLog
        traces = sorted((inside(RUNTIME / 'auto')).glob('*/requests'))
        if not traces:
            self.info(self.t('requests_empty')); return
        folder = traces[-1]
        text = RequestLog(folder.parent).preview(limit=3)
        if not text:
            self.info(self.t('requests_empty')); return
        dialog = QDialog(self.win)
        dialog.setWindowTitle(self.t('requests_title') + ' · ' + folder.parent.name)
        dialog.resize(900, 700)
        layout = QVBoxLayout(dialog); layout.setContentsMargins(14, 14, 14, 12); layout.setSpacing(8)
        viewer = QPlainTextEdit(); viewer.setReadOnly(True); viewer.setPlainText(text)
        layout.addWidget(self.label('requests_hint', objectName='hint', wrap=True))
        layout.addWidget(viewer, 1)
        row = QHBoxLayout(); row.addStretch(1)
        row.addWidget(self.button('close', dialog.accept))
        layout.addLayout(row)
        dialog.exec()

    def _render_auto(self):
        tree = self.auto_results
        tree.clear()
        if not self._auto_records:
            self._placeholder(tree, self.t('auto_empty'))
            return
        self._filled(tree)
        for record in self._auto_records:
            detail = self._auto_detail(record)
            item = QTreeWidgetItem([record.get('video', ''), detail])
            item.setToolTip(0, record.get('video', ''))
            item.setToolTip(1, detail)
            if record.get('draft'):
                item.setToolTip(1, detail + '\n\n' + str(record['draft']))
            tree.addTopLevelItem(item)
        tree.header().setSectionResizeMode(0, QHeaderView.Interactive)
        tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        tree.header().resizeSection(0, max(210, tree.fontMetrics().horizontalAdvance('BV1tK8q6fEU4:1') + 48))
        tree.scrollToBottom()

    # ----- prompts tab -----
    def build_prompts(self):
        p = self.pages['prompts_tab']
        v = QVBoxLayout(p); v.setContentsMargins(24, 18, 24, 16); v.setSpacing(8)
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(self.label('prompt_preset'))
        self.preset_combo = QComboBox(); _fixed(self.preset_combo, 280)
        row.addWidget(self.preset_combo)
        row.addWidget(self.button('prompt_load', self.load_preset))
        row.addStretch(1)
        row.addWidget(self.button('save', self.save))
        v.addLayout(row)
        v.addWidget(self.label('prompt_hint', objectName='hint', wrap=True))
        v.addWidget(self.label('prompt_editor'))
        self.prompt_editor = QPlainTextEdit(
            self.settings.system_prompt or preset_text(self.settings.prompt_preset, self.settings.answer_language))
        self.prompt_editor.setMinimumHeight(150)
        v.addWidget(self.prompt_editor, 3)
        row = QHBoxLayout(); row.setSpacing(18)
        self.injection_guard = self.check('injection_guard', self.settings.injection_guard)
        self.include_comments = self.check('include_comments', self.settings.include_comments)
        row.addWidget(self.injection_guard); row.addWidget(self.include_comments)
        row.addStretch(1)
        v.addLayout(row)
        v.addSpacing(4)
        v.addWidget(self.label('prompt_core'))
        self.core_preview = QPlainTextEdit(); self.core_preview.setReadOnly(True)
        self.core_preview.setMinimumHeight(120)
        v.addWidget(self.core_preview, 2)
        self.update_core_text()

    def update_core_text(self):
        if hasattr(self, 'core_preview'):
            self.set_text(self.core_preview, CORE[self.answer_language.currentText()])

    def load_preset(self):
        index = self.preset_combo.currentIndex()
        key = list(PRESETS)[index if index >= 0 else 0]
        self.prompt_preset = key
        self.prompt_editor.setPlainText(preset_text(key, self.answer_language.currentText()))
        self.injection_guard.setChecked(PRESETS[key]['guard'])
        self.include_comments.setChecked(not PRESETS[key]['exclude_comments'])
        self.update_core_text()

    # ----- settings tab -----
    def build_settings(self):
        body = QWidget(); body.setObjectName('surface')
        form = FormGrid(body, label_width=176)
        s = self.settings

        form.heading(self.label('group_service', objectName='section'))
        self.provider_combo = QComboBox(); self.provider_combo.addItems(['custom', 'OpenAI', 'DeepSeek', 'local'])
        _bounded(self.provider_combo, 190)
        row_widget = QWidget()
        row = QHBoxLayout(row_widget); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(8)
        row.addWidget(self.provider_combo)
        row.addWidget(self.button('provider_apply', self.apply_provider))
        row.addStretch(1)
        form.add(self.label('provider_preset'), row_widget)
        self.base_url = QLineEdit(s.base_url)
        self.model = QLineEdit(s.model)
        self.key_edit = QLineEdit(self.key_value); self.key_edit.setEchoMode(QLineEdit.Password)
        for field in (self.base_url, self.model, self.key_edit):
            field.setClearButtonEnabled(True)
            _bounded(field, 620)
        form.add(self.label('base_url'), self.base_url)
        form.add(self.label('model'), self.model)
        form.add(self.label('api_key'), self.key_edit)
        form.rule()

        form.heading(self.label('group_capability', objectName='section'))
        self.flag_checks = {}
        for key in ('require_api_key', 'remember_key', 'vision', 'function_tools', 'asr'):
            w = self.check(key, bool(getattr(s, key)))
            self.flag_checks[key] = w
            form.full(w)
        self.choice_combos = {}
        for key, values, width in [('answer_language', ['cn', 'en'], 150),
                                   ('instruction_role', ['system', 'developer'], 200),
                                   ('token_limit_parameter', ['max_tokens', 'max_completion_tokens', 'omit'], 280)]:
            w = QComboBox(); w.addItems(values); w.setCurrentText(getattr(s, key))
            self.choice_combos[key] = w
            form.add(self.label(key), _bounded(w, width))
        self.answer_language = self.choice_combos['answer_language']
        self.answer_language.currentTextChanged.connect(lambda _: self.update_core_text())
        form.rule()

        form.heading(self.label('group_limits', objectName='section'))
        self.int_spins = {}
        for key, lo, hi in [('initial_frames', 0, 8), ('extra_frames', 0, 8), ('max_minutes', 1, 120),
                            ('max_download_mb', 16, 1024), ('max_output_tokens', 64, 64000),
                            ('api_timeout_seconds', 10, 600)]:
            w = QSpinBox(); w.setRange(lo, hi); w.setValue(int(getattr(s, key)))
            self.int_spins[key] = w
            form.add(self.label(key), _bounded(w, 150))
        form.rule()

        form.heading(self.label('group_request', objectName='section'))
        form.full(self.label('request_extra_json', wrap=True))
        self.extra_editor = QPlainTextEdit(s.request_extra_json)
        self.extra_editor.setFixedHeight(88)
        self.extra_editor.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace; font-size: 12px;")
        form.full(self.extra_editor)
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(self.button('save', self.save, accent=True))
        row.addWidget(self.button('test_api', self.test_api))
        row.addStretch(1)
        form.add(None, self._layout_holder(row), span=2)
        form.full(self.label('settings_hint', objectName='hint', wrap=True))

        page = self.pages['settings_tab']
        layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_scrollable(body))

    @staticmethod
    def _layout_holder(layout: QHBoxLayout) -> QWidget:
        holder = QWidget()
        holder.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return holder

    def apply_provider(self):
        mode = self.provider_combo.currentText()
        presets = {'OpenAI': ('https://api.openai.com/v1', '', True),
                   'DeepSeek': ('https://api.deepseek.com', 'deepseek-flash', True),
                   'local': ('http://127.0.0.1:11434/v1', '', False)}
        if mode not in presets: return
        base, model, required = presets[mode]
        if self.base_url.text().rstrip('/') != base:
            self.key_edit.setText(''); self.flag_checks['remember_key'].setChecked(False)
        self.base_url.setText(base); self.model.setText(model)
        self.flag_checks['require_api_key'].setChecked(required)
        self.extra_editor.setPlainText('{"thinking":{"type":"disabled"}}' if mode == 'DeepSeek' else '{}')
        self.set_status(self.t('provider_changed'))

    # ----- diagnostics tab -----
    def build_diagnostics(self):
        p = self.pages['diagnostics_tab']
        v = QVBoxLayout(p); v.setContentsMargins(24, 18, 24, 16); v.setSpacing(8)
        v.addWidget(self.label('runtime_hint', objectName='hint', wrap=True))
        self.paths = QPlainTextEdit(); self.paths.setReadOnly(True)
        self.paths.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace; font-size: 12px;")
        v.addWidget(self.paths, 1)
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(self.button('refresh', self.refresh_paths))
        row.addWidget(self.button('save_diagnostics', self.diagnostics))
        row.addStretch(1)
        v.addLayout(row)
        self.refresh_paths()

    def refresh_paths(self):
        self.set_text(self.paths, json.dumps(path_report(), ensure_ascii=False, indent=2))

    def diagnostics(self):
        p = inside(RUNTIME / 'exports' / 'paths.json'); atomic_json(p, path_report())
        self.info(self.t('exported').format(path=p))

    # ----- i18n -----
    def change_language(self, *_):
        default_question = self.question.toPlainText().strip() in (tr('default_question', 'cn'), tr('default_question', 'en'))
        self.lang = self.lang_combo.currentText().lower()
        if default_question:
            self.question.setPlainText(self.t('default_question'))
        self.settings.language = self.lang
        try:
            self.settings.save()
        except Exception as e:
            self.error(e)
        self.translate()

    def translate(self):
        self.win.setWindowTitle(self.t('app_title'))
        for w, key in self.text_bindings:
            w.setText(self.t(key))
        for i, k in enumerate(self.pages):
            self.tabs.setTabText(i, self.t(k))
        self.frames.setHeaderLabels([self.t('time'), self.t('requested'), self.t('source')])
        self.comment_tree.setHeaderLabels([self.t('author'), self.t('uid'), self.t('content')])
        self.auto_results.setHeaderLabels([self.t('auto_target'), self.t('auto_result')])
        self._render_frames()
        self._render_comments()
        self._render_auto()
        self._render_video_header()
        self.update_targets()
        names = [PRESETS[k]['name'][0 if self.lang == 'cn' else 1] for k in PRESETS]
        current = self.settings.prompt_preset
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear(); self.preset_combo.addItems(names)
        self.preset_combo.setCurrentIndex(list(PRESETS).index(getattr(self, 'prompt_preset', current)))
        self.preset_combo.blockSignals(False)
        self.update_core_text()
        if not self.future:
            self.set_status(self.t('ready'))

    def update_targets(self):
        self.reply_label.setText(self.t('reply_to') + ': ' + self.reply['name'] + ' · ' + self.reply['rpid']
                                 if self.reply else self.t('new_comment_mode'))
        self.mention_label.setText(self.t('mentions') + ': ' + (
            ' · '.join('@' + m.name + ' (UID ' + m.uid + ')' for m in self.mentions) or self.t('none')))

    # ----- settings / plan -----
    def read_settings(self):
        s = self.settings
        values = {name: getattr(s, name) for name in vars(s)}
        values['language'] = self.lang
        values['base_url'] = self.base_url.text().strip()
        values['model'] = self.model.text().strip()
        values['system_prompt'] = self.prompt_editor.toPlainText().strip()
        values['request_extra_json'] = self.extra_editor.toPlainText().strip() or '{}'
        values['prompt_preset'] = getattr(self, 'prompt_preset', s.prompt_preset)
        values['injection_guard'] = self.injection_guard.isChecked()
        values['include_comments'] = self.include_comments.isChecked()
        for name, w in self.flag_checks.items():
            values[name] = w.isChecked()
        for name, w in self.choice_combos.items():
            values[name] = w.currentText()
        for name, w in self.int_spins.items():
            values[name] = w.value()
        return Settings(**values).validate()

    def read_auto_plan(self):
        values = {}
        for name in vars(self.auto_plan):
            if name == 'queue_text':
                values[name] = self.auto_queue.toPlainText().strip()
                continue
            w = self.auto_widgets[name]
            if isinstance(w, QSpinBox):
                values[name] = w.value()
            elif isinstance(w, QCheckBox):
                values[name] = w.isChecked()
            elif isinstance(w, QComboBox):
                values[name] = w.currentText()
            else:
                values[name] = w.text()
        values['owner_uid'] = values['owner_uid'].strip()
        values['start_time'] = values['start_time'].strip()
        return AutoPlan(**values).validate()

    def save_auto(self):
        try:
            plan = self.read_auto_plan(); plan.save(); self.auto_plan = plan
            self.set_status(self.t('auto_saved'))
        except Exception as e:
            self.error(e)

    def set_auto_enabled(self, enabled: bool):
        blocked = self.auto_enabled.blockSignals(True)
        self.auto_enabled.setChecked(enabled)
        self.auto_enabled.blockSignals(blocked)

    def toggle_auto(self):
        if not self.auto_enabled.isChecked():
            if self.auto_running: self.cancel()
            return
        if self.future:
            self.set_auto_enabled(False)
            self.info(self.t('busy')); return
        try:
            plan = self.read_auto_plan(); settings = self.read_settings()
            if plan.publish_comments and not self._auto_publish_confirmed(plan):
                self.set_auto_enabled(False); return
            plan.save(); self.auto_plan = plan
            self.reply = None; self.mentions.clear(); self.update_targets()
            self.auto_running = True
            self.task(self.service.run_auto(plan, settings, self.key_edit.text().strip()), self.auto_done)
        except Exception as e:
            self.auto_running = False; self.set_auto_enabled(False); self.error(e)

    def _auto_publish_confirmed(self, plan) -> bool:
        # Publication is an irreversible external action, so it is confirmed
        # once per switch-on instead of being enabled by a silent checkbox.
        if plan.run_until_stopped:
            scope = self.t('auto_confirm_scope_always').format(
                analysis=plan.daily_analysis_limit, posts=plan.daily_post_limit,
                owner=plan.owner_daily_limit if plan.mention_owner else 0)
        else:
            scope = self.t('auto_confirm_scope_session').format(
                videos=plan.max_videos, posts=plan.max_posts,
                owner=plan.owner_daily_limit if plan.mention_owner else 0)
        body = self.t('auto_confirm_body').format(publish=scope) + '\n\n' + self.t('auto_confirm_note')
        answer = QMessageBox.question(self.win, self.t('auto_confirm_title'), body,
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def auto_done(self, report):
        self.auto_running = False; self.set_auto_enabled(False)
        self.set_status(self.t('auto_ended') + self._auto_status(report['status']))

    def save(self):
        try:
            settings = self.read_settings()
            save_key(self.key_edit.text().strip(), settings.remember_key)
            settings.save(); self.settings = settings
            remember_secret(self.key_edit.text().strip())
            self.set_status(self.t('saved'))
        except Exception as e:
            self.error(e)

    # ----- task plumbing -----
    def task(self, awaitable, on_done):
        if self.future:
            awaitable.close()
            self.info(self.t('busy')); return
        self.future = self.service.submit(awaitable)
        self.set_status(self.t('analyzing'))
        self.future.add_done_callback(lambda f: self.queue.put(('done', f, on_done)))

    def poll(self):
        try:
            while True:
                item = self.queue.get_nowait()
                if item[0] == 'progress':
                    self.set_status(self.t(item[1]) + str(item[2]))
                elif item[0] == 'auto_video':
                    self.analysis_done(item[1])
                elif item[0] == 'auto_update':
                    self._append_auto(item[1])
                elif item[0] == 'done':
                    _, future, callback = item; self.future = None
                    if self.closing: continue
                    try:
                        value = future.result(); callback(value)
                    except Exception as e:
                        self.auto_running = False; self.set_auto_enabled(False); self.error(e)
        except queue.Empty:
            pass

    def error(self, error):
        code = getattr(error, 'code', str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__)
        detail = getattr(error, 'detail', '')
        # Never render raw HTTP bodies, credentials, cookies or signed media URLs.
        text = self.t(code)
        if text == code:
            text = ('请检查设置及项目内日志。' if self.lang == 'cn' else 'Check settings and project-local logs.') + '\n' + redact(code)
        if detail:
            text += '\n' + redact(detail)[:300]
        log.error('Operation failed code=%s', redact(code))
        self.set_status(self.t('error') + ' · ' + code)
        QMessageBox.critical(self.win, self.t('error'), text)

    # ----- actions -----
    def login_done(self, _):
        self.set_status(self.t('login_message'))

    def analyze(self):
        try:
            settings = self.read_settings(); key = self.key_edit.text().strip(); remember_secret(key)
            question = self.question.toPlainText().strip() or self.t('default_question')
            if self.future: return
            # Clear reply/mention state when changing videos to avoid misdirected writes.
            self.reply = None; self.mentions.clear(); self.update_targets()
            self.task(self.service.analyze(self.target_edit.text(), question, settings, key), self.analysis_done)
        except Exception as e:
            self.error(e)

    def analysis_done(self, ev):
        self.display_evidence = ev
        self._render_video_header()
        text = ev.answer
        if ev.notes:
            text += '\n\n' + self.t('notes') + '\n' + '\n'.join('• ' + x for x in ev.notes)
        self.set_text(self.result, text)
        self._render_frames()
        self.fill_comments(ev.comments)
        self.set_status(self.t('complete'))

    def show_frame(self, *_):
        items = self.frames.selectedItems()
        if not items:
            current = self.frames.currentItem()
            items = [current] if current is not None else []
        evidence = self.display_evidence
        if not items or not evidence: return
        index = items[0].data(0, Qt.UserRole)
        if index is None: return
        try:
            frame = evidence.frames[int(index)]
            pixmap = QPixmap(str(inside(ROOT / frame['path'])))
            if pixmap.isNull(): raise AppError('FRAME_LOAD')
            screen = self.win.screen() or QApplication.primaryScreen()
            available = screen.availableGeometry().size() if screen else QSize(1280, 800)
            limit = QSize(max(480, int(available.width() * 0.86)), max(360, int(available.height() * 0.82)))
            pixmap = pixmap.scaled(limit, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            dialog = QDialog(self.win)
            dialog.setWindowTitle(self.t('frame_dialog') + ' · ' + timestamp(frame['actual_s']))
            dialog.setAttribute(Qt.WA_DeleteOnClose, True)
            layout = QVBoxLayout(dialog); layout.setContentsMargins(14, 14, 14, 12); layout.setSpacing(8)
            view = QLabel(); view.setPixmap(pixmap); view.setAlignment(Qt.AlignCenter)
            layout.addWidget(view)
            meta = QLabel(self.t('requested') + ' ' + timestamp(frame['requested_s']) + ' · ' + self._source_label(frame.get('source', '')))
            meta.setObjectName('hint')
            layout.addWidget(meta)
            row = QHBoxLayout(); row.addStretch(1)
            close = self.button('close', dialog.accept)
            row.addWidget(close)
            layout.addLayout(row)
            dialog.exec()
        except Exception as e:
            self.error(e)

    def export(self):
        if self.future: return
        try:
            p = self.service.export()
            self.info(self.t('exported').format(path=p))
        except Exception as e:
            self.error(e)

    def fill_comments(self, comments):
        self._comments = list(comments or [])
        self._render_comments()

    def _render_comments(self):
        tree = self.comment_tree
        tree.clear()
        if not self._comments:
            self._placeholder(tree, self.t('comments_empty'))
            return
        self._filled(tree)
        for i, c in enumerate(self._comments):
            message = ' '.join(str(c.get('message', '')).split())
            item = QTreeWidgetItem([c.get('name', ''), c.get('uid', ''), message])
            item.setData(0, Qt.UserRole, i)
            item.setToolTip(0, c.get('name', ''))
            item.setToolTip(1, c.get('uid', ''))
            item.setToolTip(2, message)
            tree.addTopLevelItem(item)
        tree.header().setSectionResizeMode(0, QHeaderView.Interactive)
        tree.header().setSectionResizeMode(1, QHeaderView.Interactive)
        tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        tree.header().resizeSection(0, 180)
        tree.header().resizeSection(1, 150)

    def fetch_comments(self): self.task(self.service.comments(), self.fill_comments)

    def select_reply(self):
        if self.future: return
        if self.display_evidence is not self.service.evidence:
            self.error(AppError('LOAD_FIRST')); return
        items = self.comment_tree.selectedItems()
        if not items or items[0].data(0, Qt.UserRole) is None:
            self.info(self.t('no_selection')); return
        self.reply = self.service.evidence.comments[items[0].data(0, Qt.UserRole)].copy()
        self.update_targets()

    def clear_reply(self):
        self.reply = None; self.update_targets()

    def clear_mentions(self):
        self.mentions.clear(); self.update_targets()

    def add_mention(self):
        def done(m):
            if len(self.mentions) >= 5 or any(x.uid == m.uid or x.name == m.name for x in self.mentions):
                raise AppError('MENTION_AMBIGUOUS')
            self.mentions.append(m); self.uid.setText(''); self.update_targets()
        self.task(self.service.browser.lookup_user(self.uid.text().strip()), done)

    def draft(self):
        try:
            settings = self.read_settings()
            self.task(self.service.draft(self.t('draft_instruction'), settings, self.key_edit.text()), self.draft_done)
        except Exception as e:
            self.error(e)

    def draft_done(self, text):
        self.compose.setPlainText(text)

    def test_api(self):
        try:
            self.task(self.service.api_test(self.read_settings(), self.key_edit.text()),
                      lambda _: self.set_status(self.t('api_ok')))
        except Exception as e:
            self.error(e)

    def publish(self):
        if self.future: return
        try:
            ev = self.service.evidence
            if not ev or ev is not self.display_evidence: raise AppError('LOAD_FIRST')
            text = self.compose.toPlainText().strip()
            mentions = list(self.mentions)
            root = int(self.reply['root']) if self.reply else 0
            parent = int(self.reply['rpid']) if self.reply else 0
            preview = comment_payload(ev.aid, text, mentions, 'preview', root, parent)['message']
            target = (self.reply['name'] + ' · ' + str(parent)) if self.reply else self.t('new_comment_mode')
            notice = ev.title + '\n' + ev.url + '\n' + target + '\n' + self.mention_label.text() + '\n\n' + preview + '\n\n' + self.t('preview_footer')
            if QMessageBox.question(self.win, self.t('preview_title'), notice) == QMessageBox.Yes:
                self.task(self.service.publish(text, mentions, root, parent), self.published)
        except Exception as e:
            self.error(e)

    def published(self, value):
        text = self.t('posted').format(rpid=value['rpid'])
        if not value['mentions_confirmed']:
            text += '\n' + self.t('mention_unverified')
        self.info(text)
        self.set_status(text)

    def cancel(self):
        if self.future:
            self.service.stop.set(); self.set_auto_enabled(False); self.set_status(self.t('cancel_pending'))

    # ----- lifecycle -----
    def close_event(self, event):
        if self.closing:
            event.accept(); return
        self.closing = True
        self.set_status(self.t('closing'))
        if self.future: self.future.cancel()
        f = self.service.shutdown()
        event.ignore()

        def wait(n=0):
            if f.done() or n >= 200:
                self.win.close()
            else:
                QTimer.singleShot(100, lambda: wait(n + 1))
        # Re-arm closeEvent so the forced close succeeds.
        self.win.closeEvent = lambda e: e.accept()
        wait()

    def run(self):
        self.win.show()
        return self.app.exec()
