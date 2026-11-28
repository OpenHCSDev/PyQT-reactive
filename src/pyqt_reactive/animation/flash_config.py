"""Qt refresh-rate provider and flash configuration re-exports over formbridge.animation."""

from __future__ import annotations

import logging

from formbridge.animation import (
    COMPLETE_PHASE,
    FADE_IN_PHASE,
    FADE_OUT_PHASE,
    HOLD_PHASE,
    CompletePhase,
    FadeInPhase,
    FadeOutPhase,
    FlashConfig,
    FlashPhase,
    FlashPlayback,
    FlashRefreshRateProvider,
    HoldPhase,
    TimedFlashPhase,
    get_flash_config,
    set_flash_config,
    set_flash_refresh_rate_provider,
)

logger = logging.getLogger(__name__)


def detect_screen_refresh_rate() -> int:
    """Detect primary screen refresh rate in Hz, defaulting to 60."""
    try:
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app is None:
            logger.warning("[FlashConfig] No QApplication instance, defaulting to 60Hz")
            return 60

        screen = app.primaryScreen()
        if screen is None:
            logger.warning("[FlashConfig] No primary screen found, defaulting to 60Hz")
            return 60

        refresh_rate = screen.refreshRate()
        if refresh_rate < 30 or refresh_rate > 500:
            logger.warning(
                "[FlashConfig] Unusual refresh rate detected: %sHz, defaulting to 60Hz",
                refresh_rate,
            )
            return 60

        logger.info("[FlashConfig] Detected screen refresh rate: %sHz", refresh_rate)
        return int(refresh_rate)
    except Exception as error:
        logger.warning("[FlashConfig] Failed to detect refresh rate: %s, defaulting to 60Hz", error)
        return 60


class QtRefreshRateProvider(FlashRefreshRateProvider):
    """Qt display refresh-rate provider backed by QGuiApplication.primaryScreen()."""

    def refresh_rate_hz(self) -> int:
        return detect_screen_refresh_rate()


set_flash_refresh_rate_provider(QtRefreshRateProvider())

__all__ = [
    "COMPLETE_PHASE",
    "CompletePhase",
    "FADE_IN_PHASE",
    "FADE_OUT_PHASE",
    "FadeInPhase",
    "FadeOutPhase",
    "FlashConfig",
    "FlashPhase",
    "FlashPlayback",
    "HOLD_PHASE",
    "HoldPhase",
    "QtRefreshRateProvider",
    "TimedFlashPhase",
    "detect_screen_refresh_rate",
    "get_flash_config",
    "set_flash_config",
]
