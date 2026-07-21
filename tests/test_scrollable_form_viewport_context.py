from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLineEdit, QScrollArea, QWidget

from pyqt_reactive.widgets.shared.scrollable_form_mixin import (
    ScrollableFormMixin,
    ScrollTarget,
)


class _NavigationHarness(QWidget, ScrollableFormMixin):
    def __init__(
        self,
        scroll_area: QScrollArea,
        *,
        exact_target: ScrollTarget | None,
        fallback_target: ScrollTarget,
    ) -> None:
        super().__init__()
        self.scroll_area = scroll_area
        self.form_manager = SimpleNamespace()
        self.exact_target = exact_target
        self.fallback_target = fallback_target
        self.flashed: list[ScrollTarget] = []

    def _resolve_scroll_target(
        self,
        field_name: str,
        *,
        warn_missing: bool = True,
    ) -> ScrollTarget | None:
        del field_name, warn_missing
        return self.exact_target

    def _resolve_nearest_ancestor_scroll_target(
        self,
        field_name: str,
    ) -> ScrollTarget:
        del field_name
        return self.fallback_target

    def _flash_scroll_target(self, target: ScrollTarget) -> None:
        self.flashed.append(target)


def _scroll_target(
    field_name: str,
    widget: QWidget,
    *,
    is_field: bool,
) -> ScrollTarget:
    return ScrollTarget(
        field_name=field_name,
        leaf_name=field_name.rsplit(".", 1)[-1],
        section_path=field_name.rsplit(".", 1)[0],
        target_widget=widget,
        groupbox_widget=None,
        current_manager=SimpleNamespace(),
        is_field=is_field,
    )


def _scroll_fixture(qapp):
    scroll_area = QScrollArea()
    content = QWidget()
    content.resize(500, 1200)
    scroll_area.setWidget(content)
    scroll_area.resize(500, 220)
    scroll_area.show()
    qapp.processEvents()
    return scroll_area, content


def test_visible_fallback_context_preserves_viewport_and_focus(qapp) -> None:
    scroll_area, content = _scroll_fixture(qapp)
    fallback_widget = QWidget(content)
    fallback_widget.setGeometry(10, 200, 460, 700)
    focused_editor = QLineEdit(fallback_widget)
    focused_editor.setGeometry(20, 210, 180, 30)
    fallback = _scroll_target("config.section", fallback_widget, is_field=False)
    owner = _NavigationHarness(
        scroll_area,
        exact_target=None,
        fallback_target=fallback,
    )

    try:
        scroll_area.activateWindow()
        focused_editor.setFocus(Qt.FocusReason.OtherFocusReason)
        scroll_area.verticalScrollBar().setValue(350)
        qapp.processEvents()
        initial_value = scroll_area.verticalScrollBar().value()
        assert qapp.focusWidget() is focused_editor

        for _ in range(3):
            owner.select_and_scroll_to_field("config.section.rows[1].value")
            qapp.processEvents()
            assert scroll_area.verticalScrollBar().value() == initial_value
            assert qapp.focusWidget() is focused_editor

        assert owner.flashed == [fallback, fallback, fallback]
    finally:
        scroll_area.close()


def test_offscreen_fallback_moves_only_enough_to_reveal_it(qapp) -> None:
    scroll_area, content = _scroll_fixture(qapp)
    fallback_widget = QWidget(content)
    fallback_widget.setGeometry(10, 700, 460, 50)
    fallback = _scroll_target("config.section", fallback_widget, is_field=False)
    owner = _NavigationHarness(
        scroll_area,
        exact_target=None,
        fallback_target=fallback,
    )

    try:
        scroll_area.verticalScrollBar().setValue(200)
        qapp.processEvents()
        viewport_height = scroll_area.viewport().height()

        owner.select_and_scroll_to_field("config.section.rows[1].value")
        qapp.processEvents()

        assert scroll_area.verticalScrollBar().value() == 750 - viewport_height
        viewport = owner._scroll_viewport()
        assert owner._target_is_fully_visible(fallback, viewport)
    finally:
        scroll_area.close()


def test_large_offscreen_fallback_reveals_only_its_nearest_edge(qapp) -> None:
    scroll_area, content = _scroll_fixture(qapp)
    fallback_widget = QWidget(content)
    fallback_widget.setGeometry(10, 200, 460, 500)
    fallback = _scroll_target("config.section", fallback_widget, is_field=False)
    owner = _NavigationHarness(
        scroll_area,
        exact_target=None,
        fallback_target=fallback,
    )

    try:
        viewport_height = scroll_area.viewport().height()
        scroll_area.verticalScrollBar().setValue(800)
        qapp.processEvents()

        owner.select_and_scroll_to_field("config.section.rows[1].value")
        qapp.processEvents()
        assert scroll_area.verticalScrollBar().value() == 699

        fallback_widget.setGeometry(10, 800, 460, 350)
        scroll_area.verticalScrollBar().setValue(200)
        qapp.processEvents()

        owner.select_and_scroll_to_field("config.section.rows[1].value")
        qapp.processEvents()
        assert scroll_area.verticalScrollBar().value() == 800 - viewport_height + 1
    finally:
        scroll_area.close()


def test_exact_and_fallback_navigation_repeats_without_context_drift(qapp) -> None:
    scroll_area, content = _scroll_fixture(qapp)
    fallback_widget = QWidget(content)
    fallback_widget.setGeometry(10, 200, 460, 700)
    exact_widget = QLineEdit(fallback_widget)
    exact_widget.setGeometry(20, 500, 180, 30)
    fallback = _scroll_target("config.section", fallback_widget, is_field=False)
    exact = _scroll_target("config.section.rows[1].value", exact_widget, is_field=True)
    owner = _NavigationHarness(
        scroll_area,
        exact_target=None,
        fallback_target=fallback,
    )

    try:
        scroll_area.verticalScrollBar().setValue(350)
        qapp.processEvents()
        initial_value = scroll_area.verticalScrollBar().value()

        owner.select_and_scroll_to_field(exact.field_name)
        assert scroll_area.verticalScrollBar().value() == initial_value

        owner.exact_target = exact
        owner.select_and_scroll_to_field(exact.field_name)
        exact_value = scroll_area.verticalScrollBar().value()
        assert exact_value > initial_value
        assert owner._target_is_fully_visible(exact, owner._scroll_viewport())

        owner.exact_target = None
        owner.select_and_scroll_to_field(exact.field_name)
        assert scroll_area.verticalScrollBar().value() == exact_value

        owner.exact_target = exact
        owner.select_and_scroll_to_field(exact.field_name)
        assert scroll_area.verticalScrollBar().value() == exact_value
    finally:
        scroll_area.close()
