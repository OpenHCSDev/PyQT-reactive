"""Declarative configuration for flash animations."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class FlashPhase(Enum):
    """Declared presentation phases; timing starts at admission/paint acknowledgement."""

    FADE_IN = (lambda config: config.fade_in_s, lambda progress: progress * (2 - progress), True)
    HOLD = (lambda config: config.hold_s, lambda progress: 1.0, False)
    FADE_OUT = (lambda config: config.fade_out_s,
                lambda progress: 1 - (4 * progress ** 3 if progress < 0.5 else 1 - (-2 * progress + 2) ** 3 / 2), False)
    COMPLETE = (lambda config: 0.0, lambda progress: 0.0, False)

    def __init__(self, duration_for, opacity_for, awaits_maximum: bool):
        self._duration_for = duration_for
        self._opacity_for = opacity_for
        self.awaits_maximum = awaits_maximum

    def duration(self, config: "FlashConfig") -> float:
        return self._duration_for(config)

    def next_phase(self) -> "FlashPhase":
        phases = tuple(FlashPhase)
        return phases[min(phases.index(self) + 1, len(phases) - 1)]

    def alpha(self, progress: float, maximum: int) -> int:
        return int(maximum * self._opacity_for(progress))


@dataclass(eq=False)
class FlashPlayback:
    """One phase/clock authority, including genuine maximum-paint admission.

    GUI stalls can extend wall time. They cannot consume an unpresented maximum
    or the declared hold interval. Recipients are derived visible window owners,
    not another animation registry; disappearing recipients stop participating.
    Identity is the cohort identity: several independently addressable keys can
    share this exact mutable presentation record without copying its clock.
    """

    phase_started_at: float
    pending_recipients: set[tuple[int, str]] = field(default_factory=set)
    phase: FlashPhase = FlashPhase.FADE_IN

    def _advance(self, now: float) -> None:
        self.phase = self.phase.next_phase()
        self.phase_started_at = now

    def sample_alpha(self, now: float, config: "FlashConfig") -> int:
        duration = self.phase.duration(config)
        elapsed = max(0.0, now - self.phase_started_at)
        if not self.phase.awaits_maximum and elapsed >= duration:
            self._advance(now)
            duration = self.phase.duration(config)
            elapsed = 0.0
        progress = min(1.0, elapsed / duration) if duration > 0 else 1.0
        return self.phase.alpha(progress, config.flash_alpha)

    def acknowledge(self, recipient: tuple[int, str], alpha: int, now: float, config: "FlashConfig") -> None:
        if self.phase.awaits_maximum and alpha == config.flash_alpha:
            self.pending_recipients.discard(recipient)
            if not self.pending_recipients:
                self._advance(now)

    def retain_recipients(self, visible: set[tuple[int, str]]) -> None:
        self.pending_recipients.intersection_update(visible)


def detect_screen_refresh_rate() -> int:
    """Detect primary screen refresh rate.

    Returns:
        Detected refresh rate (Hz), or 60 if detection fails.
    """
    try:
        from PyQt6.QtGui import QGuiApplication

        # Get primary screen (QGuiApplication has primaryScreen() method)
        app = QGuiApplication.instance()
        if app is None:
            logger.warning("[FlashConfig] No QApplication instance, defaulting to 60Hz")
            return 60

        screen = app.primaryScreen()
        if screen is None:
            logger.warning("[FlashConfig] No primary screen found, defaulting to 60Hz")
            return 60

        refresh_rate = screen.refreshRate()

        # Sanity check: typical refresh rates are 60, 75, 120, 144, 165, 240
        if refresh_rate < 30 or refresh_rate > 500:
            logger.warning(f"[FlashConfig] Unusual refresh rate detected: {refresh_rate}Hz, defaulting to 60Hz")
            return 60

        logger.info(f"[FlashConfig] Detected screen refresh rate: {refresh_rate}Hz")
        return int(refresh_rate)
    except Exception as e:
        logger.warning(f"[FlashConfig] Failed to detect refresh rate: {e}, defaulting to 60Hz")
        return 60


@dataclass
class FlashConfig:
    """Flash animation tuning knobs with automatic screen refresh rate detection."""

    base_color_rgb: Tuple[int, int, int] = (255, 255, 255)  # Medium grey for no-scope flashes
    flash_alpha: int = 255
    fade_in_s: float = 0.200
    hold_s: float = 0.050
    fade_out_s: float = 0.600

    # Frame rate configuration
    frame_ms: Optional[int] = None  # Auto-calculated from target_fps if not specified

    # OpenGL acceleration (EXPERIMENTAL - actually slower than QPainter in practice)
    # The overhead of GL context switching and buffer uploads exceeds the benefit
    # of instanced rendering for our typical workload (few rectangles, simple shapes).
    # Keep False unless explicitly testing GL performance.
    use_opengl: bool = False

    # High refresh rate support
    # Options: None (auto-detect), 30, 60, 144, 240, or any custom value
    # None = automatically matches screen refresh rate (recommended)
    target_fps: Optional[int] = None  # None = auto-detect screen refresh rate

    # Advanced: Cap refresh rate even if screen supports higher
    max_fps: Optional[int] = 60# None = no cap, or set to limit (e.g., 60 for power saving)

    @property
    def total_duration_s(self) -> float:
        """Full configured animation interval, including both fades and hold."""
        return sum(phase.duration(self) for phase in FlashPhase)

    def __post_init__(self):
        """Calculate frame_ms from target_fps or auto-detect screen refresh rate."""
        # If frame_ms explicitly set, use it
        if self.frame_ms is not None:
            return

        # Determine target FPS
        fps = self.target_fps
        if fps is None:
            # Auto-detect screen refresh rate
            fps = detect_screen_refresh_rate()
            logger.info(f"[FlashConfig] Auto-detected target FPS: {fps}")

        # Apply max_fps cap if specified
        if self.max_fps is not None and fps > self.max_fps:
            logger.info(f"[FlashConfig] Capping FPS from {fps} to {self.max_fps} (max_fps limit)")
            fps = self.max_fps

        # Calculate frame interval
        self.frame_ms = int(1000 / fps)
        logger.info(f"[FlashConfig] Using {fps}Hz ({self.frame_ms}ms frame interval) for flash animations")


_config: Optional[FlashConfig] = None


def get_flash_config() -> FlashConfig:
    """Return singleton flash config."""
    global _config
    if _config is None:
        _config = FlashConfig()
    return _config
