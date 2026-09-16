"""Declared presentation is admitted by actual consumers, not skipped wall phases."""

import pytest

from pyqt_reactive.animation.flash_config import FlashConfig, FlashPhase, FlashPlayback


@pytest.fixture
def config():
    return FlashConfig(frame_ms=16)


def test_slow_first_frame_cannot_consume_the_maximum_or_hold(config):
    source = (10, "container:20")
    playback = FlashPlayback(1.0, {source})
    assert playback.sample_alpha(4.0, config) == 255
    assert playback.phase is FlashPhase.FADE_IN
    playback.acknowledge(source, 254, 4.0, config)
    assert playback.phase is FlashPhase.FADE_IN
    playback.acknowledge(source, 255, 4.1, config)
    assert playback.phase is FlashPhase.HOLD
    assert playback.sample_alpha(4.149, config) == 255
    assert playback.sample_alpha(4.151, config) == 255
    assert playback.phase is FlashPhase.FADE_OUT
    assert playback.sample_alpha(4.751, config) == 0
    assert playback.phase is FlashPhase.COMPLETE
    assert config.total_duration_s == pytest.approx(0.85)


def test_every_visible_source_must_present_maximum_even_in_the_same_window(config):
    group, row = (10, "container:20"), (10, "source:tree:30")
    playback = FlashPlayback(0.0, {group, row})
    playback.acknowledge(row, 255, 1.0, config)
    assert playback.phase is FlashPhase.FADE_IN
    assert playback.sample_alpha(2.0, config) == 255
    playback.acknowledge(group, 255, 2.0, config)
    assert playback.phase_started_at == 2.0
    assert playback.phase is FlashPhase.HOLD


def test_hidden_or_disposed_source_does_not_block_remaining_presentation(config):
    visible, disappeared = (10, "source:a"), (20, "source:b")
    playback = FlashPlayback(0.0, {visible, disappeared})
    playback.retain_recipients({visible})
    playback.acknowledge(visible, 255, 1.0, config)
    assert playback.phase is FlashPhase.HOLD


def test_retrigger_has_a_fresh_phase_and_recipient_contract(config):
    source = (10, "source:a")
    old = FlashPlayback(0.0, {source})
    old.acknowledge(source, 255, 1.0, config)
    retrigger = FlashPlayback(2.0, {source})
    assert retrigger.sample_alpha(2.0, config) == 0
    assert retrigger.phase is FlashPhase.FADE_IN
    assert retrigger.pending_recipients == {source}


@pytest.mark.parametrize("phase", tuple(FlashPhase))
def test_phase_leaves_own_duration_and_opacity(config, phase):
    assert phase.duration(config) >= 0
    assert 0 <= phase.alpha(0.5, config.flash_alpha) <= config.flash_alpha


@pytest.fixture
def actual_surfaces(qapp):
    from PyQt6 import sip
    from PyQt6.QtWidgets import QDialog, QPushButton, QVBoxLayout
    from pyqt_reactive.animation.flash_mixin import WindowFlashOverlay, _GlobalFlashCoordinator, create_widget_rect_element

    coordinator = _GlobalFlashCoordinator.get()
    coordinator._playbacks.clear()
    coordinator._computed_colors.clear()
    coordinator._pending_flash_keys.clear()
    windows, overlays = [], []

    def create(*keys):
        window = QDialog()
        layout = QVBoxLayout(window)
        for key in keys:
            layout.addWidget(QPushButton(key))
        window.show()
        qapp.processEvents()
        overlay = WindowFlashOverlay.get_for_window(window)
        for key, button in zip(keys, window.findChildren(QPushButton)):
            overlay.register_element(create_widget_rect_element(key, button))
        windows.append(window)
        overlays.append(overlay)
        return window, overlay

    yield coordinator, create
    if coordinator._timer is not None:
        coordinator._timer.stop()
    coordinator._playbacks.clear()
    coordinator._computed_colors.clear()
    coordinator._pending_flash_keys.clear()
    coordinator._active_windows.clear()
    for window in windows:
        if not sip.isdeleted(window):
            WindowFlashOverlay.cleanup_window(window)
            window.close()
            window.deleteLater()


def test_native_subset_retrigger_drops_former_only_recipients_from_old_cohort(actual_surfaces, qtbot):
    coordinator, create = actual_surfaces
    window, overlay = create("first", "second")
    painted = []
    overlay.frame_painted.connect(painted.append)
    coordinator.queue_flash_batch(("first", "second"))
    coordinator._flush_pending_flash_keys()
    old = coordinator._playbacks["second"]
    assert coordinator._playbacks["first"] is old
    assert len(old.pending_recipients) == 2
    coordinator.queue_flash("first")
    coordinator._flush_pending_flash_keys()
    retrigger = coordinator._playbacks["first"]
    assert retrigger is not old
    coordinator._on_global_tick()
    assert len(old.pending_recipients) == 1
    assert len(retrigger.pending_recipients) == 1
    qtbot.waitUntil(lambda: old.phase is FlashPhase.HOLD and retrigger.phase is FlashPhase.HOLD, timeout=1500)
    assert any(element.key == "second" and element.rgba[3] == 255
               for frame in painted for element in frame.elements)


@pytest.mark.parametrize("disappears", ("hidden", "disposed"))
def test_native_hidden_or_disposed_window_cannot_block_exposed_peer(actual_surfaces, qtbot, qapp, disappears):
    from PyQt6.QtCore import QEvent
    coordinator, create = actual_surfaces
    first, overlay = create("first")
    second, _ = create("second")
    painted = []
    overlay.frame_painted.connect(painted.append)
    coordinator.queue_flash_batch(("first", "second"))
    coordinator._flush_pending_flash_keys()
    playback = coordinator._playbacks["first"]
    assert coordinator._playbacks["second"] is playback
    assert len(playback.pending_recipients) == 2
    if disappears == "hidden":
        second.hide()
    else:
        second.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qtbot.waitUntil(lambda: playback.phase is FlashPhase.HOLD, timeout=1500)
    assert "second" not in coordinator._playbacks
    assert any(frame.has_maximum_alpha for frame in painted)
