"""Headless Qt checks for the desktop layout.

These run against an offscreen platform, so they need no display and no
network. They cover the interaction defects that were reported: a single
click must only select, the wheel must scroll the page rather than rewrite a
value, and empty tables must not paint stray cells.
"""
from __future__ import annotations
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

try:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractItemView, QApplication, QDialog, QLineEdit, QMessageBox
except ImportError:  # Qt is optional; the Tkinter fallback has no such tests.
    QApplication = None

from biliscope.domain import Evidence
from biliscope.runtime import RUNTIME, inside


@unittest.skipIf(QApplication is None, 'PySide6 is not installed')
class QtLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from biliscope.ui_qt import App
        cls.ui = App()
        cls.win = cls.ui.win
        cls.win.resize(1280, 940)
        cls.win.show()
        cls._pump()

    @classmethod
    def tearDownClass(cls):
        cls.ui.timer.stop()
        cls.win.close()
        cls._pump()

    @classmethod
    def _pump(cls, rounds=12):
        for _ in range(rounds):
            cls.app.processEvents()

    # ----- fixtures -----
    def _frame_path(self) -> str:
        # Written under runtime/tmp so the test never looks like real evidence.
        folder = inside(RUNTIME / 'tmp' / 'ui-test-frames')
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / 'frame-0000010000.png'
        if not target.exists():
            from PySide6.QtGui import QPixmap
            pixmap = QPixmap(64, 36)
            pixmap.fill(Qt.white)
            pixmap.save(str(target))
        return str(target.relative_to(inside(RUNTIME.parent)))

    def _evidence(self) -> Evidence:
        evidence = Evidence('BV1xx411c7mD', 1, 1, 300, 'Fixture title', 'https://www.bilibili.com/video/BV1xx411c7mD/', 300, 300)
        evidence.answer = 'A short answer used by the layout tests.'
        evidence.comments = [
            {'rpid': '1', 'root': '0', 'uid': '10001', 'name': 'First viewer', 'message': 'Comment one', 'likes': 0},
            {'rpid': '2', 'root': '0', 'uid': '10002', 'name': 'Second viewer', 'message': 'Comment two', 'likes': 0},
        ]
        evidence.frames = [
            {'actual_s': 10.0, 'requested_s': 10.0, 'source': 'initial', 'path': self._frame_path()},
            {'actual_s': 20.0, 'requested_s': 20.0, 'source': 'extra-request', 'path': self._frame_path()},
        ]
        evidence.notes = []
        return evidence

    def _click_row(self, tree, row=0, column=None):
        item = tree.topLevelItem(row)
        point = tree.visualItemRect(item).center()
        if column is not None:
            point.setX(tree.visualItemRect(item).left() + tree.columnViewportPosition(column) + 8)
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        self._pump()

    # ----- helpers that make each test independent of the previous one -----
    def _activate(self, tree):
        ui = self.ui
        if tree is ui.auto_results:
            ui.tabs.setCurrentWidget(ui.pages['auto_tab'])
        elif tree is ui.comment_tree:
            ui.tabs.setCurrentWidget(ui.pages['comment_tab'])
        else:
            ui.tabs.setCurrentWidget(ui.pages['video_tab'])
        self._pump()

    def setUp(self):
        ui = self.ui
        ui.display_evidence = None
        ui._comments = []
        ui._auto_records = []
        ui.lang = 'cn'
        ui.translate()
        self._pump()

    # ----- single click only selects -----
    def test_single_click_selects_without_side_effects(self):
        ui = self.ui
        ui.analysis_done(self._evidence())
        self._pump()
        with patch.object(QDialog, 'exec', lambda self, *a, **k: 0), \
             patch.object(QMessageBox, 'information', lambda *a, **k: None), \
             patch.object(QMessageBox, 'critical', lambda *a, **k: None):
            for tree in (ui.frames, ui.comment_tree):
                self._activate(tree)
                tree.clearSelection()
                self._click_row(tree)
                self.assertEqual(len(tree.selectedItems()), 1, tree.objectName() or type(tree).__name__)
                # A single click must not enter an editor.
                self.assertEqual(tree.state(), QAbstractItemView.NoState)
                self.assertEqual(tree.findChildren(QLineEdit), [])

    def test_single_click_does_not_open_frame_dialog(self):
        ui = self.ui
        ui.analysis_done(self._evidence())
        self._pump()
        opened = []
        with patch('biliscope.ui_qt.QDialog.exec', lambda self, *a, **k: opened.append(self.windowTitle())):
            self._activate(ui.frames)
            ui.frames.clearSelection()
            self._click_row(ui.frames)
            self._click_row(ui.frames, row=1)
            self._pump()
            self.assertEqual(opened, [])

    def test_double_click_still_opens_frame(self):
        ui = self.ui
        ui.analysis_done(self._evidence())
        self._pump()
        opened = []
        with patch('biliscope.ui_qt.QDialog.exec', lambda self, *a, **k: opened.append(self.windowTitle())):
            self._activate(ui.frames)
            item = ui.frames.topLevelItem(0)
            rect = ui.frames.visualItemRect(item)
            # A user selects the row first, then double-clicks it.
            QTest.mouseClick(ui.frames.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
            self._pump(4)
            QTest.mouseDClick(ui.frames.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
            self._pump()
        self.assertEqual(len(opened), 1)

    def test_clicked_row_stays_within_viewport(self):
        ui = self.ui
        ui.analysis_done(self._evidence())
        self._activate(ui.frames)
        rect = ui.frames.visualItemRect(ui.frames.topLevelItem(0))
        self.assertGreaterEqual(rect.top(), 0)
        self.assertLessEqual(rect.bottom(), ui.frames.viewport().height())

    # ----- wheel must not mutate values -----
    def _wheel(self, widget, delta=-120):
        point = QPointF(widget.rect().center())
        event = QWheelEvent(point, widget.mapToGlobal(point), QPoint(0, 0), QPoint(0, delta),
                            Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
        QApplication.sendEvent(widget, event)
        self._pump(4)

    def test_wheel_over_unfocused_spinbox_scrolls_page(self):
        ui = self.ui
        ui.tabs.setCurrentWidget(ui.pages['settings_tab'])
        self._pump()
        scroll = ui.pages['settings_tab'].layout().itemAt(0).widget()
        bar = scroll.verticalScrollBar()
        bar.setValue(0)
        spin = ui.int_spins['max_minutes']
        ui.base_url.setFocus()
        self._pump()
        before = spin.value()
        self._wheel(spin)
        self.assertEqual(spin.value(), before)
        self.assertGreater(bar.value(), 0)

    def test_wheel_over_unfocused_combobox_scrolls_page(self):
        ui = self.ui
        ui.tabs.setCurrentWidget(ui.pages['settings_tab'])
        self._pump()
        scroll = ui.pages['settings_tab'].layout().itemAt(0).widget()
        bar = scroll.verticalScrollBar()
        bar.setValue(0)
        combo = ui.choice_combos['answer_language']
        ui.base_url.setFocus()
        self._pump()
        before = combo.currentText()
        self._wheel(combo)
        self.assertEqual(combo.currentText(), before)
        self.assertGreater(bar.value(), 0)

    def test_focused_spinbox_keeps_native_wheel(self):
        ui = self.ui
        ui.tabs.setCurrentWidget(ui.pages['settings_tab'])
        self._pump()
        spin = ui.int_spins['max_minutes']
        spin.setFocus()
        self._pump()
        before = spin.value()
        self._wheel(spin, delta=-120)
        self.assertNotEqual(spin.value(), before)

    def test_auto_page_wheel_scrolls_instead_of_editing(self):
        ui = self.ui
        ui.tabs.setCurrentWidget(ui.pages['auto_tab'])
        self._pump()
        area = ui.pages['auto_tab'].layout().itemAt(0).widget()
        bar = area.verticalScrollBar()
        bar.setValue(0)
        spin = ui.auto_widgets['interval_minutes']
        ui.target_edit.setFocus()
        self._pump()
        before = spin.value()
        self._wheel(spin)
        self.assertEqual(spin.value(), before)
        self.assertGreater(bar.value(), 0)

    # ----- layout sanity -----
    def test_empty_tables_show_hint_without_phantom_rows(self):
        ui = self.ui
        ui.display_evidence = None
        ui._comments = []
        ui._auto_records = []
        ui._render_frames(); ui._render_comments(); ui._render_auto()
        self._pump()
        for tree in (ui.frames, ui.comment_tree, ui.auto_results):
            self.assertEqual(tree.topLevelItemCount(), 0)
            self.assertFalse(tree.empty_state.isHidden())

    def test_rows_hide_empty_hint(self):
        ui = self.ui
        ui.analysis_done(self._evidence())
        self._pump()
        self.assertGreater(ui.frames.topLevelItemCount(), 0)
        self.assertTrue(ui.frames.empty_state.isHidden())

    def test_scroll_pages_have_no_horizontal_overflow(self):
        ui = self.ui
        for key in ('auto_tab', 'settings_tab'):
            ui.tabs.setCurrentWidget(ui.pages[key])
            self._pump()
            page = ui.pages[key]
            area = page.layout().itemAt(0).widget()
            self.assertEqual(area.horizontalScrollBar().maximum(), 0, key)
            self.assertLessEqual(area.widget().width(), area.viewport().width() + 1, key)

    def test_form_fields_have_bounded_width(self):
        ui = self.ui
        ui.tabs.setCurrentWidget(ui.pages['settings_tab'])
        self._pump()
        for name, widget in list(ui.int_spins.items()) + list(ui.choice_combos.items()):
            self.assertLessEqual(widget.width(), 640, name)

    def test_table_columns_fit_header_text(self):
        ui = self.ui
        ui.tabs.setCurrentWidget(ui.pages['video_tab'])
        ui.analysis_done(self._evidence())
        self._pump()
        header = ui.frames.header()
        metrics = ui.frames.fontMetrics()
        for column, key in ((0, 'time'), (1, 'requested')):
            needed = metrics.horizontalAdvance(ui.t(key)) + 18
            self.assertGreaterEqual(header.sectionSize(column), needed, key)

    def test_prompt_editor_keeps_action_buttons_visible(self):
        ui = self.ui
        ui.tabs.setCurrentWidget(ui.pages['prompts_tab'])
        self._pump()
        # Buttons live above the editors, so a tall prompt cannot push them away.
        for button in ui.pages['prompts_tab'].findChildren(type(ui.view_frame_btn)):
            if button.text() == ui.t('save'):
                self.assertTrue(button.isVisible())

    def test_empty_state_text_tracks_language(self):
        ui = self.ui
        seen = {}
        for lang in ('cn', 'en'):
            ui.lang = lang
            ui.translate()
            self._pump()
            seen[lang] = ui.frames.empty_state.text()
        self.assertNotEqual(seen['cn'], seen['en'])


if __name__ == '__main__':
    unittest.main()
