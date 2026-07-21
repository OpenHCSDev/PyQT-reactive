"""Regression tests for flash clipping to the target's own scroll hierarchy."""

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QDialog, QGroupBox, QScrollArea, QVBoxLayout, QWidget


def _viewport_rect_in_window(scroll_area: QScrollArea, window: QWidget) -> QRect:
    viewport = scroll_area.viewport()
    position = window.mapFromGlobal(viewport.mapToGlobal(QPoint(0, 0)))
    return QRect(position, viewport.size())


def test_groupbox_flash_clips_to_owning_scroll_viewport_not_sibling(qapp) -> None:
    """A tall target must never be clipped into an unrelated sibling viewport."""

    from pyqt_reactive.animation.flash_mixin import (
        WindowFlashOverlay,
        create_groupbox_element,
    )

    dialog = QDialog()
    dialog.resize(420, 460)
    layout = QVBoxLayout(dialog)

    owning_scroll = QScrollArea()
    owning_scroll.setWidgetResizable(False)
    config_group = QGroupBox("Viewer Config")
    config_group.setFixedSize(380, 340)
    owning_scroll.setWidget(config_group)

    sibling_scroll = QScrollArea()
    sibling_scroll.setWidgetResizable(True)
    sibling_scroll.setWidget(QWidget())

    layout.addWidget(owning_scroll, 1)
    layout.addWidget(sibling_scroll, 1)
    dialog.show()
    for _ in range(5):
        qapp.processEvents()

    overlay = WindowFlashOverlay.get_for_window(config_group)
    assert overlay is not None
    element = create_groupbox_element("viewer_config.port", config_group)
    overlay.register_element(element)

    target_rect = element.get_rect_in_window(dialog)
    assert target_rect is not None
    owning_clip = _viewport_rect_in_window(owning_scroll, dialog)
    sibling_clip = _viewport_rect_in_window(sibling_scroll, dialog)
    assert target_rect.intersects(owning_clip)
    assert target_rect.intersects(sibling_clip)

    # Put the unrelated viewport first to reproduce the Image Browser ordering.
    overlay._rebuild_geometry_cache(
        [sibling_clip, owning_clip],
        {"viewer_config.port"},
    )

    cached_rect, _radius = overlay._cache.element_rects["viewer_config.port"][0]
    assert cached_rect == target_rect.intersected(owning_clip)

    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()


def test_groupbox_flash_intersects_every_owning_scroll_viewport(qapp) -> None:
    """Nested scroll ownership constrains a target through the full hierarchy."""

    from pyqt_reactive.animation.flash_mixin import (
        WindowFlashOverlay,
        create_groupbox_element,
    )

    dialog = QDialog()
    dialog.resize(440, 360)
    layout = QVBoxLayout(dialog)

    outer_scroll = QScrollArea()
    outer_scroll.setWidgetResizable(False)
    outer_content = QWidget()
    outer_content.setFixedSize(410, 520)
    outer_layout = QVBoxLayout(outer_content)

    inner_scroll = QScrollArea()
    inner_scroll.setWidgetResizable(False)
    inner_scroll.setFixedSize(390, 260)
    config_group = QGroupBox("Viewer Config")
    config_group.setFixedSize(370, 440)
    inner_scroll.setWidget(config_group)
    outer_layout.addSpacing(120)
    outer_layout.addWidget(inner_scroll)
    outer_layout.addStretch()
    outer_scroll.setWidget(outer_content)
    layout.addWidget(outer_scroll)

    dialog.show()
    for _ in range(5):
        qapp.processEvents()

    overlay = WindowFlashOverlay.get_for_window(config_group)
    assert overlay is not None
    element = create_groupbox_element("viewer_config.host", config_group)
    overlay.register_element(element)

    target_rect = element.get_rect_in_window(dialog)
    assert target_rect is not None
    outer_clip = _viewport_rect_in_window(outer_scroll, dialog)
    inner_clip = _viewport_rect_in_window(inner_scroll, dialog)
    expected = target_rect.intersected(inner_clip).intersected(outer_clip)
    assert expected.isValid()

    overlay._rebuild_geometry_cache([], {"viewer_config.host"})

    cached_rect, _radius = overlay._cache.element_rects["viewer_config.host"][0]
    assert cached_rect == expected

    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()


def test_groupbox_outside_scroll_areas_ignores_unrelated_viewport(qapp) -> None:
    """An unrelated scroll area never clips a target with no scroll ancestor."""

    from pyqt_reactive.animation.flash_mixin import (
        WindowFlashOverlay,
        create_groupbox_element,
    )

    dialog = QDialog()
    dialog.resize(420, 360)
    layout = QVBoxLayout(dialog)
    config_group = QGroupBox("Viewer Config")
    config_group.setFixedHeight(180)
    unrelated_scroll = QScrollArea()
    unrelated_scroll.setWidget(QWidget())
    layout.addWidget(config_group)
    layout.addWidget(unrelated_scroll)

    dialog.show()
    for _ in range(5):
        qapp.processEvents()

    overlay = WindowFlashOverlay.get_for_window(config_group)
    assert overlay is not None
    element = create_groupbox_element("viewer_config.port", config_group)
    overlay.register_element(element)
    target_rect = element.get_rect_in_window(dialog)
    assert target_rect is not None

    unrelated_clip = _viewport_rect_in_window(unrelated_scroll, dialog)
    overlay._rebuild_geometry_cache(
        [unrelated_clip],
        {"viewer_config.port"},
    )

    cached_rect, _radius = overlay._cache.element_rects["viewer_config.port"][0]
    assert cached_rect == target_rect

    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()
