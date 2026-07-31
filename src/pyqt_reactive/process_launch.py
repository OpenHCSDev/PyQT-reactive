"""Platform policy for noninteractive background subprocesses.

The module is intentionally standard-library-only.  It is safe to import from
early startup paths before either Qt or the rest of pyqt-reactive is loaded.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from enum import Enum


class BackgroundProcessPlatform(Enum):
    """Host families with distinct background-process behavior."""

    WINDOWS = "win32"
    OTHER = "other"

    @classmethod
    def current(cls) -> BackgroundProcessPlatform:
        """Return the current host family."""

        if sys.platform == cls.WINDOWS.value:
            return cls.WINDOWS
        return cls.OTHER


@dataclass(frozen=True, slots=True)
class BackgroundProcessLaunchSpec:
    """Resolved keyword arguments for one subprocess launch."""

    creationflags: int = 0
    start_new_session: bool = False

    def popen_arguments(self) -> dict[str, bool | int]:
        """Return only non-default ``subprocess.Popen`` arguments."""

        arguments: dict[str, bool | int] = {}
        if self.creationflags:
            arguments["creationflags"] = self.creationflags
        if self.start_new_session:
            arguments["start_new_session"] = True
        return arguments


@dataclass(frozen=True, slots=True)
class BackgroundProcessLaunchPolicy:
    """Own console suppression and detached process-group behavior."""

    platform: BackgroundProcessPlatform
    detached: bool = False

    @classmethod
    def current(
        cls,
        *,
        detached: bool = False,
    ) -> BackgroundProcessLaunchPolicy:
        """Construct the policy for the current host."""

        return cls(
            platform=BackgroundProcessPlatform.current(),
            detached=detached,
        )

    def resolve(self) -> BackgroundProcessLaunchSpec:
        """Resolve the platform policy to a transportable launch spec."""

        if self.platform is BackgroundProcessPlatform.WINDOWS:
            creationflags = subprocess.CREATE_NO_WINDOW
            if self.detached:
                creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
            return BackgroundProcessLaunchSpec(creationflags=creationflags)
        return BackgroundProcessLaunchSpec(start_new_session=self.detached)

    def popen_arguments(self) -> dict[str, bool | int]:
        """Resolve directly to ``subprocess.Popen`` keyword arguments."""

        return self.resolve().popen_arguments()
