"""Actual Qt paint geometry for nested parameter-form flash feedback."""

from dataclasses import dataclass, field

import objectstate.config as config_module
import pytest
from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QPainterPath
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout

from pyqt_reactive.animation.flash_mixin import (
    LEAF_WIDGET_TYPES,
    NativeLabelCoverageSurface,
    WindowFlashOverlay,
    _GlobalFlashCoordinator,
    get_child_mask_path,
    get_child_mask_rect,
    resolve_mask_widgets,
)
from pyqt_reactive.forms.parameter_form_manager import (
    FormManagerConfig,
    ParameterFormManager,
)
from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.clickable_help_components import HelpIndicator


@pytest.fixture
def nested_form(qapp):
    @dataclass
    class Child:
        alpha: int = 1
        beta: int = 2

    @dataclass
    class Root:
        child: Child = field(default_factory=Child)

    previous_base = config_module._base_config_type
    set_base_config_type(Root)
    ObjectStateRegistry.clear()
    host = QDialog()
    host.resize(600, 350)
    layout = QVBoxLayout(host)
    manager = ParameterFormManager(
        ObjectState(Root()),
        FormManagerConfig(color_scheme=ColorScheme(), use_scroll_area=False),
    )
    layout.addWidget(manager)
    host.show()
    qapp.processEvents()
    yield host, manager.nested_managers["child"]
    coordinator = _GlobalFlashCoordinator.get()
    if coordinator._timer is not None:
        coordinator._timer.stop()
    coordinator._computed_colors.clear()
    coordinator._playbacks.clear()
    coordinator._pending_flash_keys.clear()
    WindowFlashOverlay.cleanup_window(host)
    host.close()
    host.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    ObjectStateRegistry.clear()
    config_module._base_config_type = previous_base


@pytest.mark.parametrize("text", ["Alpha:", "A longer parameter label:"])
@pytest.mark.parametrize("width", [100, 220])
@pytest.mark.parametrize("underline", [False, True])
@pytest.mark.parametrize("point_size", [9, 12])
@pytest.mark.parametrize("italic", [False, True])
def test_label_mask_has_padded_native_hull_and_respects_alignment_and_style(
    nested_form, qapp, text, width, underline, point_size, italic
):
    host, manager = nested_form
    label = manager.labels["alpha"].findChild(QLabel)
    label.setText(text)
    font = label.font()
    font.setUnderline(underline)
    font.setPointSize(point_size)
    font.setItalic(italic)
    label.setFont(font)
    label.setWordWrap(True)
    label.setFixedSize(width, 112)
    manager.labels["alpha"].setMinimumSize(width + 40, 120)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
    label.setStyleSheet("color: white; background: #141414; padding: 4px; margin: 2px;")
    qapp.processEvents()
    rect = label.rect().translated(label.mapTo(host, QPoint()))
    mask = get_child_mask_rect(label, host)
    mask_path = get_child_mask_path(label, host)
    assert mask.width() < rect.width()
    assert mask.height() < rect.height()
    contents = label.contentsRect().translated(label.mapTo(host, QPoint()))
    # Native italic glyphs can overhang the layout contents rectangle.
    padding = NativeLabelCoverageSurface.MASK_PADDING_PX
    assert rect.adjusted(-int(padding), -int(padding), int(padding), int(padding)).contains(mask)
    image = label.grab().toImage()
    ratio = image.devicePixelRatio()
    text_pixels = [
        QPointF((x + 0.5) / ratio, (y + 0.5) / ratio)
        for y in range(image.height())
        for x in range(image.width())
        if max(image.pixelColor(x, y).getRgb()[:3]) > 20 and image.pixelColor(x, y).alpha() > 0
    ]
    assert text_pixels
    origin = QPointF(label.mapTo(host, QPoint()))
    outside = [point for point in text_pixels if not mask_path.contains(point + origin)]
    assert not outside, (mask, contents, outside[:10])
    assert mask_path.boundingRect().left() == pytest.approx(
        origin.x() + min(point.x() for point in text_pixels) - 0.5 / ratio - padding,
        abs=0.02,
    )
    assert mask_path.boundingRect().right() == pytest.approx(
        origin.x() + max(point.x() for point in text_pixels) + 0.5 / ratio + padding,
        abs=0.02,
    )
    assert mask_path.boundingRect().top() == pytest.approx(
        origin.y() + min(point.y() for point in text_pixels) - 0.5 / ratio - padding,
        abs=0.02,
    )
    assert mask_path.boundingRect().bottom() == pytest.approx(
        origin.y() + max(point.y() for point in text_pixels) + 0.5 / ratio + padding,
        abs=0.02,
    )
    assert any(
        not mask_path.contains(QPointF(x + 0.5, y + 0.5))
        for y in range(mask.top(), mask.bottom() + 1)
        for x in range(mask.left(), mask.right() + 1)
    ), "The padded hull must retain its sloped/rounded outline"


def test_label_mask_gives_letter_interiors_and_word_spaces_one_convex_backing(nested_form, qapp):
    host, manager = nested_form
    label = manager.labels["alpha"].findChild(QLabel)
    label.setText("O     O")
    font = label.font()
    font.setPointSize(32)
    font.setUnderline(False)
    label.setFont(font)
    label.setFixedSize(240, 80)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    qapp.processEvents()

    path = get_child_mask_path(label, host)
    contours = path.simplified().toSubpathPolygons()
    assert len(contours) == 1
    bounds = path.boundingRect()
    center = bounds.center()
    assert path.contains(center), "Word spaces share the whole label's backing"
    assert path.contains(QPointF(bounds.left() + 10, center.y()))
    assert path.contains(QPointF(bounds.right() - 10, center.y()))


def test_empty_label_has_no_flash_mask(nested_form, qapp):
    host, manager = nested_form
    label = manager.labels["alpha"].findChild(QLabel)
    label.setText("")
    qapp.processEvents()
    assert get_child_mask_path(label, host).isEmpty()


def test_native_label_capture_preserves_source_and_releases_temporary_children(nested_form):
    host, manager = nested_form
    label = manager.labels["alpha"].findChild(QLabel)
    before = (label.text(), label.font(), label.styleSheet(), label.geometry(), label.children())
    for _ in range(3):
        assert not get_child_mask_path(label, host).isEmpty()
    after = (label.text(), label.font(), label.styleSheet(), label.geometry(), label.children())
    assert after == before


def test_native_label_capture_does_not_notify_live_hierarchy_observers(nested_form):
    class ChildObserver(QObject):
        def __init__(self):
            super().__init__()
            self.events = []

        def eventFilter(self, watched, event):  # noqa: N802 - Qt virtual method name
            if event.type() in {QEvent.Type.ChildAdded, QEvent.Type.ChildRemoved}:
                self.events.append(event.type())
            return False

    host, manager = nested_form
    label = manager.labels["alpha"].findChild(QLabel)
    observer = ChildObserver()
    label.installEventFilter(observer)
    assert not get_child_mask_path(label, host).isEmpty()
    assert observer.events == []


@pytest.mark.parametrize("fields", [("alpha",), ("alpha", "beta")])
def test_nested_flash_paint_has_opaque_context_and_complete_clear_holes(nested_form, qapp, fields):
    host, manager = nested_form
    for name in fields:
        manager.update_parameter(name, 10)
    qapp.processEvents()
    overlay = WindowFlashOverlay.get_for_window(host)
    coordinator = _GlobalFlashCoordinator.get()
    if coordinator._timer is not None:
        coordinator._timer.stop()
    coordinator._computed_colors.clear()
    keys = {f"child.{name}" for name in fields}
    import time
    from pyqt_reactive.animation.flash_config import FlashPlayback, FlashPhase
    coordinator._playbacks.clear()
    coordinator._playbacks.update({key: FlashPlayback(time.perf_counter(), phase=FlashPhase.HOLD) for key in keys})
    coordinator._key_base_colors.update({key: QColor(255, 0, 0) for key in keys})
    coordinator._computed_colors.update({key: QColor(255, 0, 0, 255) for key in keys})
    overlay._rebuild_geometry_cache([], keys)
    records, _ = overlay._visible_paint_records(keys, colors=coordinator._computed_colors)
    assert len(records) == 1
    record = records[0]
    assert record.color.alpha() == 255
    title = overlay._elements["child.alpha"][0].container._title_label
    assert record.path.intersected(get_child_mask_path(title, host)).simplified().isEmpty()
    for name in fields:
        labels = resolve_mask_widgets(manager.labels[name], LEAF_WIDGET_TYPES)
        indicator = manager.labels[name].findChild(HelpIndicator)
        assert indicator is not None
        assert get_child_mask_rect(indicator, host) == indicator.rect().translated(
            indicator.mapTo(host, QPoint())
        )
        for widget in (*labels, manager.widgets[name]):
            mask_path = get_child_mask_path(widget, host)
            assert record.path.intersected(mask_path).simplified().isEmpty()

    image = overlay.grab().toImage()
    ratio = image.devicePixelRatio()
    for name in fields:
        point = manager.widgets[name].mapTo(host, manager.widgets[name].rect().center())
        assert image.pixelColor(int(point.x() * ratio), int(point.y() * ratio)).alpha() == 0
    painted = [
        image.pixelColor(int(x * ratio), int(y * ratio))
        for y in range(record.rect.top() + 2, record.rect.bottom() - 2)
        for x in range(record.rect.left() + 2, record.rect.right() - 2)
        if record.path.contains(QPointF(x + 0.5, y + 0.5))
    ]
    assert any(color.alpha() == 255 and color.red() == 255 for color in painted)


def test_overlapping_flash_phases_retain_all_active_holes(nested_form, qapp):
    host, manager = nested_form
    for name in ("alpha", "beta"):
        manager.update_parameter(name, 10)
    qapp.processEvents()
    overlay = WindowFlashOverlay.get_for_window(host)
    colors = {
        "child.alpha": QColor(255, 0, 0, 64),
        "child.beta": QColor(0, 0, 255, 255),
    }
    overlay._rebuild_geometry_cache([], set(colors))
    records, _ = overlay._visible_paint_records(set(colors), colors=colors)
    assert len(records) == 1
    assert records[0].color == colors["child.beta"]
    for name in ("alpha", "beta"):
        widget = manager.widgets[name]
        assert not records[0].path.contains(QPointF(widget.mapTo(host, widget.rect().center())))

    remaining, _ = overlay._visible_paint_records({"child.beta"}, colors=colors)
    alpha = manager.widgets["alpha"]
    beta = manager.widgets["beta"]
    assert remaining[0].path.contains(QPointF(alpha.mapTo(host, alpha.rect().center())))
    assert not remaining[0].path.contains(QPointF(beta.mapTo(host, beta.rect().center())))


def test_materialized_leaf_retires_its_lazy_container_mask(nested_form, qapp):
    host, manager = nested_form
    manager.update_parameter("alpha", 10)
    qapp.processEvents()
    overlay = WindowFlashOverlay.get_for_window(host)
    container = overlay._elements["child.alpha"][0].container
    root = manager.form_tree.root()
    root.register_flash_groupbox("child.alpha", container)
    assert len(overlay._elements["child.alpha"]) == 2
    root.register_flash_leaf(
        "child.alpha", container, manager.widgets["alpha"], manager.labels["alpha"]
    )
    assert len(overlay._elements["child.alpha"]) == 1
    overlay._rebuild_geometry_cache([], {"child.alpha"})
    records, _ = overlay._visible_paint_records({"child.alpha"})
    sibling = manager.widgets["beta"]
    assert records[0].path.contains(QPointF(sibling.mapTo(host, sibling.rect().center())))


def test_geometry_signature_retains_shape_changes_with_equal_bounds(nested_form, monkeypatch):
    """A path cache must observe shape changes even when layout bounds stay equal."""
    from pyqt_reactive.animation import flash_mixin

    host, manager = nested_form
    label = manager.labels["alpha"].findChild(QLabel)
    rectangle = QPainterPath()
    rectangle.addRect(0, 0, 20, 20)
    triangle = QPainterPath()
    triangle.moveTo(0, 0)
    triangle.lineTo(20, 20)
    triangle.lineTo(0, 20)
    triangle.closeSubpath()
    assert rectangle.boundingRect() == triangle.boundingRect()
    monkeypatch.setattr(flash_mixin, "get_child_mask_path", lambda *_: rectangle)
    previous = WindowFlashOverlay._geometry_signature(label)
    monkeypatch.setattr(flash_mixin, "get_child_mask_path", lambda *_: triangle)
    assert WindowFlashOverlay._geometry_signature(label) != previous
