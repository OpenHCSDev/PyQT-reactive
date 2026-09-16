"""Real Qt layout/paint regressions for optional manager-list preview wrapping."""

import pytest
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QListWidgetItem, QStyleOptionViewItem

from pyqt_reactive.core import ReorderableListWidget
from pyqt_reactive.widgets.shared.list_item_delegate import (
    DIRTY_FIELDS_ROLE,
    LAYOUT_ROLE,
    LEADING_MARKER_ROLE,
    ListItemLeadingMarker,
    MultilinePreviewItemDelegate,
    PREVIEW_WRAP_ROLE,
    PreviewWrapMode,
)
from pyqt_reactive.widgets.shared.list_item_text_rendering import (
    StyledTextRenderer,
    TextPaintContext,
)
from pyqt_reactive.widgets.shared.styled_text_layout import Segment, StyledTextLayout


@pytest.fixture
def preview_list(qtbot):
    view = ReorderableListWidget()
    qtbot.addWidget(view)
    view.setItemDelegate(
        MultilinePreviewItemDelegate(
            QColor("black"),
            QColor("gray"),
            QColor("white"),
            parent=view,
        )
    )
    view.resize(380, 500)
    view.show()
    return view


def test_delegate_requires_owning_list_view():
    with pytest.raises(TypeError, match="parent"):
        MultilinePreviewItemDelegate(QColor("black"), QColor("gray"), QColor("white"))


@pytest.mark.parametrize("disable_view", [False, True])
def test_disabled_disclosure_keeps_geometry_without_accepting_actions(
    qtbot, preview_list, disable_view
):
    from pyqt_reactive.services.widget_tree_projection import TogglePreviewAction

    view = preview_list
    row = add_row(view)
    view.doItemsLayout()
    index = view.indexFromItem(row)
    original_rect = arrow_rect(view, row)
    if disable_view:
        view.setEnabled(False)
    else:
        row.setFlags(row.flags() & ~Qt.ItemFlag.ItemIsEnabled)
    assert arrow_rect(view, row) == original_rect
    assert not TogglePreviewAction().available(view, index)
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=original_rect.center())
    assert row.data(PREVIEW_WRAP_ROLE) is None
    with pytest.raises(ValueError, match="enabled preview"):
        TogglePreviewAction().invoke(view, index)


def add_row(view, *, structured=True):
    text = "long_input_path/" * 35
    row = QListWidgetItem(text)
    if structured:
        row.setData(
            LAYOUT_ROLE,
            StyledTextLayout(
                name=Segment("Signal normalization", "name"),
                detail_line=text,
                preview_segments=[Segment("percentile=99.8", "percentile")],
                config_segments=[Segment("source=" + text, "source")],
                multiline=True,
            ),
        )
    view.addItem(row)
    return row


@pytest.mark.parametrize("structured", [True, False])
def test_wrap_toggle_and_viewport_resize_reflow_and_restore_scroll(qtbot, preview_list, structured):
    view = preview_list
    row = add_row(view, structured=structured)
    qtbot.waitUntil(lambda: view.horizontalScrollBar().maximum() > 0)
    compact_height = view.visualItemRect(row).height()
    view.horizontalScrollBar().setValue(100)

    view.setWordWrap(True)
    qtbot.waitUntil(lambda: view.visualItemRect(row).height() > compact_height)
    wrapped_height = view.visualItemRect(row).height()
    assert not view.horizontalScrollBar().isVisible()
    assert view.horizontalScrollBar().value() == 0
    assert view.visualItemRect(row).width() <= view.viewport().width()

    view.resize(240, 500)
    qtbot.waitUntil(lambda: view.visualItemRect(row).height() > wrapped_height)
    view.resize(650, 500)
    qtbot.waitUntil(lambda: view.visualItemRect(row).height() < wrapped_height)

    view.setWordWrap(False)
    qtbot.waitUntil(lambda: view.horizontalScrollBar().maximum() > 0)
    assert view.visualItemRect(row).height() == compact_height
    assert view.horizontalScrollBar().isVisible()


def test_wrapped_rows_update_after_content_and_font_changes(qtbot, preview_list):
    view = preview_list
    row = QListWidgetItem("short")
    view.addItem(row)
    view.setWordWrap(True)
    initial_height = view.visualItemRect(row).height()
    row.setText("a_very_long_unbroken_path/" * 80)
    qtbot.waitUntil(lambda: view.visualItemRect(row).height() > initial_height)
    text_height = view.visualItemRect(row).height()
    font = QFont(view.font())
    font.setPointSize(20)
    view.setFont(font)
    qtbot.waitUntil(lambda: view.visualItemRect(row).height() > text_height)


def test_single_wrapped_row_taller_than_viewport_can_scroll_to_last_line(qtbot, preview_list):
    view = preview_list
    view.resize(220, 150)
    row = add_row(view)
    view.setWordWrap(True)
    qtbot.waitUntil(lambda: view.verticalScrollBar().maximum() > 0)
    qtbot.waitUntil(
        lambda: view.verticalScrollBar().maximum()
        >= view.visualItemRect(row).height() - view.viewport().height()
    )
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
    assert view.visualItemRect(row).bottom() <= view.viewport().height()


def test_wrapped_row_markers_and_dirty_fields_take_measured_space(qtbot, preview_list):
    view = preview_list
    row = add_row(view)
    view.setWordWrap(True)
    before = view.visualItemRect(row).height()
    row.setData(LEADING_MARKER_ROLE, ListItemLeadingMarker())
    row.setData(DIRTY_FIELDS_ROLE, {"name", "source", "percentile"})
    qtbot.waitUntil(lambda: view.visualItemRect(row).height() >= before)
    # Paint the actual view, including the marker and row borders, without an X server.
    assert not view.grab().isNull()
    assert view.horizontalScrollBar().maximum() == 0


def test_shared_layout_preserves_unicode_field_styles_and_entire_text(qapp):
    layout = StyledTextLayout(
        name=Segment("🔬 Neurons", "name", asterisk_prefix=True),
        preview_segments=[Segment("percentile=99.8", "percentile")],
        config_segments=[Segment("path=" + "/plate/images" * 10, "path")],
        multiline=True,
    )
    renderer = StyledTextRenderer()
    context = TextPaintContext(
        {"name", "path"},
        {"percentile"},
        QFont("Sans", 12),
        QColor("white"),
        QColor("gray"),
    )
    compact = renderer.prepare(layout, context)
    wrapped = renderer.prepare(layout, context, 130)
    assert wrapped is renderer.prepare(layout, context, 130)
    assert wrapped.size.height() > compact.size.height()
    assert [p.text() for p in wrapped.paragraphs] == [p.text() for p in compact.paragraphs]
    assert "*🔬 Neurons" in wrapped.paragraphs[0].text()
    for paragraph in wrapped.paragraphs:
        encoded = paragraph.text().encode("utf-16-le")
        assert (
            sum(paragraph.lineAt(i).textLength() for i in range(paragraph.lineCount()))
            == len(encoded) // 2
        )
        for formatting in paragraph.formats():
            substring = encoded[
                formatting.start * 2 : (formatting.start + formatting.length) * 2
            ].decode("utf-16-le")
            if substring == "percentile=99.8":
                assert formatting.format.fontUnderline()


def test_single_line_layout_does_not_measure_hidden_details(qapp):
    renderer = StyledTextRenderer()
    context = TextPaintContext(set(), set(), QFont(), QColor(), QColor())
    layout = StyledTextLayout(name=Segment("Name"), detail_line="not displayed", multiline=False)
    prepared = renderer.prepare(layout, context)
    assert len(prepared.paragraphs) == 1
    assert prepared.paragraphs[0].text() == "Name"


def row_option(view, row):
    option = QStyleOptionViewItem()
    option.initFrom(view)
    option.font = view.font()
    option.rect = view.visualItemRect(row)
    return option


def arrow_rect(view, row):
    return view.itemDelegate().disclosure_rect(row_option(view, row), view.indexFromItem(row))


def test_arrow_toggles_only_its_row_and_text_click_does_not(qtbot, preview_list):
    view = preview_list
    first, second = add_row(view), add_row(view)
    view.doItemsLayout()
    initial = view.visualItemRect(first).height()
    qtbot.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, pos=arrow_rect(view, first).center()
    )
    qtbot.waitUntil(lambda: first.data(PREVIEW_WRAP_ROLE) is PreviewWrapMode.WRAPPED)
    assert second.data(PREVIEW_WRAP_ROLE) is None
    assert view.visualItemRect(first).height() > initial
    assert view.visualItemRect(second).height() == initial
    rect = arrow_rect(view, first)
    qtbot.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, pos=rect.topRight() + QPoint(40, 5)
    )
    assert first.data(PREVIEW_WRAP_ROLE) is PreviewWrapMode.WRAPPED
    qtbot.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, pos=arrow_rect(view, first).center()
    )
    qtbot.waitUntil(lambda: first.data(PREVIEW_WRAP_ROLE) is PreviewWrapMode.HORIZONTAL)
    assert view.visualItemRect(first).height() == initial


def test_global_default_changes_preserve_explicit_row_choice(qtbot, preview_list):
    view = preview_list
    first, second = add_row(view), add_row(view)
    first.setData(PREVIEW_WRAP_ROLE, PreviewWrapMode.HORIZONTAL)
    view.setWordWrap(True)
    view.doItemsLayout()
    assert view.visualItemRect(first).height() < view.visualItemRect(second).height()
    assert view.horizontalScrollBar().maximum() > 0
    third = add_row(view)
    view.doItemsLayout()
    assert view.visualItemRect(third).height() == view.visualItemRect(second).height()
    view.setWordWrap(False)
    assert view.visualItemRect(first).height() == view.visualItemRect(second).height()
    assert first.data(PREVIEW_WRAP_ROLE) is PreviewWrapMode.HORIZONTAL
    assert second.data(PREVIEW_WRAP_ROLE) is None


def test_last_horizontal_row_toggle_removes_scrollbar_and_restores_it(qtbot, preview_list):
    view = preview_list
    row = add_row(view)
    qtbot.waitUntil(lambda: view.horizontalScrollBar().maximum() > 0)
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=arrow_rect(view, row).center())
    qtbot.waitUntil(lambda: view.horizontalScrollBar().maximum() == 0)
    assert not view.horizontalScrollBar().isVisible()
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=arrow_rect(view, row).center())
    qtbot.waitUntil(lambda: view.horizontalScrollBar().maximum() > 0)


def test_mixed_rows_resize_scroll_and_keep_wrapped_text_reachable(qtbot, preview_list):
    view = preview_list
    wrapped, horizontal = add_row(view), add_row(view)
    wrapped.setData(PREVIEW_WRAP_ROLE, PreviewWrapMode.WRAPPED)
    view.doItemsLayout()
    old_height = view.visualItemRect(wrapped).height()
    view.resize(240, 300)
    qtbot.waitUntil(lambda: view.visualItemRect(wrapped).height() > old_height)
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().maximum())
    rect = arrow_rect(view, wrapped)
    assert rect.left() >= 0
    assert (
        view.itemDelegate()
        ._row_rect(row_option(view, wrapped), view.indexFromItem(wrapped))
        .width()
        == view.viewport().width()
    )
    assert arrow_rect(view, horizontal).right() < 0
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
    assert view.visualItemRect(horizontal).bottom() <= view.viewport().height()
    assert not view.grab().isNull()
    view.resize(650, 500)
    qtbot.waitUntil(lambda: view.visualItemRect(wrapped).height() < old_height)


@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize("scoped", [False, True])
def test_wrapped_text_disclosure_marker_and_flash_stay_aligned_when_scrolled(
    qtbot, preview_list, focused, scoped, monkeypatch
):
    from pathlib import Path

    from pyqt_reactive.widgets.shared.list_item_delegate import (
        OBJECT_STATE_PATH_ROLE,
        SCOPE_SCHEME_ROLE,
    )
    from pyqt_reactive.widgets.shared.config_tree_contracts import TreeFlashColorProvider
    from pyqt_reactive.widgets.shared.scope_color_utils import build_color_scheme_from_rgb

    class ActiveRowFlash(TreeFlashColorProvider):
        def get_flash_color_for_object_state_path(self, scope):
            return QColor(230, 45, 65, 200)

        def acknowledge_flash_paint(self, object_state_path, window, alpha):
            pass

    view = preview_list
    native_frames = []
    style = view.style()
    native_draw = style.drawControl

    def record_native_frame(element, option, painter, widget):
        native_frames.append((option.rect.getRect(), option.state.value))
        return native_draw(element, option, painter, widget)

    monkeypatch.setattr(style, "drawControl", record_native_frame)
    wrapped, _horizontal = add_row(view), add_row(view)
    wrapped.setData(PREVIEW_WRAP_ROLE, PreviewWrapMode.WRAPPED)
    wrapped.setData(LEADING_MARKER_ROLE, ListItemLeadingMarker())
    wrapped.setData(OBJECT_STATE_PATH_ROLE, "wrapped-row")
    if scoped:
        wrapped.setData(
            SCOPE_SCHEME_ROLE,
            build_color_scheme_from_rgb((230, 45, 65), "plate::step_3"),
        )
    view.itemDelegate()._manager = ActiveRowFlash()
    view.doItemsLayout()
    view.clearSelection()
    view.activateWindow()
    qtbot.waitUntil(view.isActiveWindow)
    if focused:
        view.setFocus()
        qtbot.waitUntil(view.hasFocus)
    else:
        view.clearFocus()
    # Native Windows recomputes hovered rows on scroll. Keep the pointer on the
    # scrollbar so this test compares the same interaction state on both sides.
    scrollbar = view.horizontalScrollBar()
    qtbot.mouseMove(scrollbar, pos=scrollbar.rect().center())
    capture_height = min(view.visualItemRect(wrapped).height(), view.viewport().height())
    native_frames.clear()
    before = view.viewport().grab().toImage().copy(0, 0, view.viewport().width(), capture_height)
    before_frames = tuple(native_frames)
    native_frames.clear()
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().maximum())
    after = view.viewport().grab().toImage().copy(0, 0, view.viewport().width(), capture_height)
    evidence = Path("test-artifacts/wrapped-row-scroll") / str(scoped) / str(focused)
    evidence.mkdir(parents=True, exist_ok=True)
    before.save(str(evidence / "before.png"))
    after.save(str(evidence / "after.png"))
    if before != after:
        view.viewport().repaint()
        repainted = (
            view.viewport().grab().toImage().copy(0, 0, view.viewport().width(), capture_height)
        )
        repainted.save(str(evidence / "repainted.png"))
        differences = [
            (x, y)
            for x in range(min(before.width(), after.width()))
            for y in range(min(before.height(), after.height()))
            if before.pixel(x, y) != after.pixel(x, y)
        ]
        print(
            "scroll pixel diagnostics",
            {
                "style": view.style().objectName(),
                "before_size": (before.width(), before.height()),
                "after_size": (after.width(), after.height()),
                "device_pixel_ratio": before.devicePixelRatio(),
                "different_pixels": len(differences),
                "difference_bounds": (
                    (
                        min(x for x, y in differences),
                        min(y for x, y in differences),
                        max(x for x, y in differences),
                        max(y for x, y in differences),
                    )
                    if differences
                    else None
                ),
                "explicit_repaint_restores_equality": before == repainted,
                "focus": view.hasFocus(),
                "before_native_frames": before_frames,
                "after_native_frames": native_frames,
                "row_rect": view.visualItemRect(wrapped).getRect(),
            },
        )
    assert {frame for frame in before_frames if frame[0][1] == 0} == {
        frame for frame in native_frames if frame[0][1] == 0
    }
    assert before == after
    view.itemDelegate()._manager = None
    unflashed = view.viewport().grab().toImage().copy(0, 0, view.viewport().width(), capture_height)
    assert after != unflashed


def test_each_visual_preview_line_has_graphical_guide_and_hanging_gutter(qapp):
    renderer = StyledTextRenderer()
    context = TextPaintContext(
        {"value"}, {"value"}, QFont("Sans", 12), QColor("black"), QColor("gray")
    )
    layout = StyledTextLayout(
        name=Segment("Header"),
        detail_line="Image location",
        preview_segments=[Segment("value=" + "long/parameter/" * 15, "value")],
        multiline=True,
    )
    prepared = renderer.prepare(layout, context, 130)
    preview = prepared.paragraphs[-1]
    assert len(prepared.line_guides) == preview.lineCount() > 3
    assert prepared.paragraphs[0].lineAt(0).x() == 0
    assert prepared.paragraphs[1].lineAt(0).x() == 0
    assert "└" not in preview.text()
    assert preview.text().endswith("*")
    for index, guide in enumerate(prepared.line_guides):
        line = preview.lineAt(index)
        assert guide.line_height > 0
        assert line.x() == guide.guide.width(line.height())
        assert line.y() == guide.position.y()
    assert preview.formats()[0].format.fontUnderline()


def test_structural_action_projects_and_toggles_same_row_authority(qtbot, preview_list):
    from pyqt_reactive.services.widget_tree_projection import (
        WidgetActionKind,
        WidgetTreeProjectionService,
    )

    view = preview_list
    first, second = add_row(view), add_row(view)
    view.doItemsLayout()
    projection = WidgetTreeProjectionService.project(view)

    def rows(descriptor):
        yield descriptor
        for child in descriptor.children:
            yield from rows(child)

    descriptors = [node for node in rows(projection.root) if node.class_name == "QModelIndex"]
    assert WidgetActionKind.ITEM_PREVIEW_TOGGLE in descriptors[0].action_kinds
    action = WidgetActionKind.ITEM_PREVIEW_TOGGLE.item_action
    action.invoke(view, view.indexFromItem(first))
    assert first.data(PREVIEW_WRAP_ROLE) is PreviewWrapMode.WRAPPED
    assert second.data(PREVIEW_WRAP_ROLE) is None
    assert WidgetActionKind.ITEM_SELECT.item_action.default
    assert not action.default


def test_disclosure_tracks_font_and_domain_marker_without_covering_text(qtbot, preview_list):
    view = preview_list
    row = add_row(view)
    row.setData(LEADING_MARKER_ROLE, ListItemLeadingMarker())
    font = QFont(view.font())
    font.setPointSize(20)
    view.setFont(font)
    view.doItemsLayout()
    target = arrow_rect(view, row)
    assert target.height() > 20
    assert target.bottom() < view.visualItemRect(row).bottom()
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=target.center())
    assert row.data(PREVIEW_WRAP_ROLE) is PreviewWrapMode.WRAPPED


def test_arrow_double_click_does_not_open_item_editor(qtbot, preview_list):
    view = preview_list
    row = add_row(view)
    view.doItemsLayout()
    opened = []
    view.itemDoubleClicked.connect(opened.append)
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=arrow_rect(view, row).center())
    qtbot.mouseDClick(
        view.viewport(), Qt.MouseButton.LeftButton, pos=arrow_rect(view, row).center()
    )
    assert opened == []


def test_disclosure_requires_press_and_release_on_same_arrow(qtbot, preview_list):
    view = preview_list
    first, second = add_row(view), add_row(view)
    view.doItemsLayout()
    first_target, second_target = arrow_rect(view, first), arrow_rect(view, second)
    qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=first_target.center())
    qtbot.mouseMove(view.viewport(), second_target.center())
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=second_target.center())
    assert first.data(PREVIEW_WRAP_ROLE) is None
    assert second.data(PREVIEW_WRAP_ROLE) is None
    qtbot.mousePress(
        view.viewport(), Qt.MouseButton.LeftButton, pos=first_target.topRight() + QPoint(40, 5)
    )
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=first_target.center())
    assert first.data(PREVIEW_WRAP_ROLE) is None


def test_manager_rebuild_reuses_row_owned_wrap_choice(qtbot, preview_list):
    from pyqt_reactive.widgets.shared.list_item_delegate import OBJECT_STATE_PATH_ROLE
    from pyqt_reactive.widgets.shared.manager_list_updater import (
        ManagerListUpdateOperations,
        ManagerListUpdater,
    )

    view = preview_list
    items = ["plate-one", "plate-two"]
    subscribed = set()
    operations = ManagerListUpdateOperations(
        item_list=view,
        backing_items=items,
        should_preserve_selection=lambda: True,
        placeholder=lambda: None,
        prepare_update=lambda: None,
        clear_scope_cache=lambda: None,
        subscribed_scope_ids=lambda: set(subscribed),
        scope_for_item=lambda item: item,
        cleanup_flash_subscriptions=subscribed.clear,
        clear_scope_to_list_item=lambda: None,
        format_item=lambda item, index, context: item,
        should_refresh_text_for_scope_change=lambda item, paths: True,
        list_item_data_for=lambda item, index: item,
        tooltip_for=lambda item: item,
        extra_data_for=lambda item, index: {},
        set_styling_roles=lambda row, text, item: row.setData(OBJECT_STATE_PATH_ROLE, item),
        refresh_styling_roles=lambda row, item: None,
        apply_scope_color=lambda row, item, index: None,
        subscribe_flash=lambda item, row, scope: subscribed.add(scope),
        post_update=lambda: None,
        update_button_states=lambda: None,
    )
    updater = ManagerListUpdater()
    updater.update(operations)
    first, second = view.item(0), view.item(1)
    first.setData(PREVIEW_WRAP_ROLE, PreviewWrapMode.WRAPPED)
    view.setCurrentItem(first)
    items.insert(0, "new-plate")
    updater.update(operations)
    assert view.item(1) is first
    assert view.item(2) is second
    assert first.data(PREVIEW_WRAP_ROLE) is PreviewWrapMode.WRAPPED
    assert first.isSelected()
    assert view.item(0).data(PREVIEW_WRAP_ROLE) is None
    items.pop()
    items.reverse()
    updater.update(operations)
    assert view.item(0) is first
    assert first.data(PREVIEW_WRAP_ROLE) is PreviewWrapMode.WRAPPED
    items.reverse()
    updater.update(operations)
    assert view.item(1) is first
    assert first.data(PREVIEW_WRAP_ROLE) is PreviewWrapMode.WRAPPED
    items.remove("plate-one")
    updater.update(operations)
    items.append("plate-one")
    updater.update(operations)
    assert view.item(1) is not first
    assert view.item(1).data(PREVIEW_WRAP_ROLE) is None
