"""Measure representative nested form construction without flaky assertions."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from dataclasses import dataclass, field
from math import ceil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type  # noqa: E402
from PyQt6 import sip  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from pyqt_reactive.forms.parameter_form_manager import (  # noqa: E402
    FormManagerConfig,
    ParameterFormManager,
)
from pyqt_reactive.theming import ColorScheme  # noqa: E402


@dataclass
class _Leaf:
    value_1: int = 1
    value_2: int = 2
    value_3: int = 3
    value_4: int = 4
    value_5: int = 5
    value_6: int = 6
    value_7: int = 7
    value_8: int = 8


@dataclass
class _Branch:
    leaf_1: _Leaf = field(default_factory=_Leaf)
    leaf_2: _Leaf = field(default_factory=_Leaf)
    leaf_3: _Leaf = field(default_factory=_Leaf)
    leaf_4: _Leaf = field(default_factory=_Leaf)


@dataclass
class _Root:
    branch_1: _Branch = field(default_factory=_Branch)
    branch_2: _Branch = field(default_factory=_Branch)
    branch_3: _Branch = field(default_factory=_Branch)
    branch_4: _Branch = field(default_factory=_Branch)


def _manager_tree(root):
    yield root
    for nested in root.nested_managers.values():
        yield from _manager_tree(nested)


def _is_ready(root) -> bool:
    return (
        all(
            len(manager.widgets) == len(manager.form_structure.parameters)
            for manager in _manager_tree(root)
        )
        and root._form_build_transaction.finalization_count == 1
    )


def _percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(ceil(0.95 * len(ordered)) - 1, 0)]


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "median_ms": statistics.median(values) * 1000,
        "p95_ms": _percentile_95(values) * 1000,
    }


def run(*, iterations: int, warmups: int, timeout_s: float) -> dict[str, object]:
    app = QApplication.instance() or QApplication([])
    set_base_config_type(_Root)
    ObjectStateRegistry.clear()
    state = ObjectState(_Root(), scope_id="benchmark::nested-form")
    samples: list[tuple[float, float, float, float]] = []
    topology = None

    for _ in range(iterations + warmups):
        started = time.perf_counter()
        manager = ParameterFormManager(
            state,
            FormManagerConfig(
                color_scheme=ColorScheme(),
                use_scroll_area=False,
            ),
        )
        constructor_s = time.perf_counter() - started
        deadline = time.perf_counter() + timeout_s
        max_slice_s = 0.0
        while not _is_ready(manager) and time.perf_counter() < deadline:
            slice_started = time.perf_counter()
            app.processEvents()
            max_slice_s = max(
                max_slice_s,
                time.perf_counter() - slice_started,
            )
        if not _is_ready(manager):
            raise TimeoutError("Nested form did not reach declared-field completion.")
        complete_s = time.perf_counter() - started
        managers = tuple(_manager_tree(manager))
        topology = {
            "manager_count": len(managers),
            "row_count": sum(len(item.widgets) for item in managers),
        }
        samples.append(
            (
                constructor_s,
                complete_s,
                max_slice_s,
                manager._form_build_transaction.max_slice_elapsed_s,
            )
        )
        manager.dispose()
        sip.delete(manager)
        app.processEvents()

    measured = samples[warmups:]
    result = {
        "iterations": iterations,
        "warmups": warmups,
        "constructor": _summary([sample[0] for sample in measured]),
        "declared_field_completion": _summary(
            [sample[1] for sample in measured]
        ),
        "maximum_event_loop_slice": _summary(
            [sample[2] for sample in measured]
        ),
        "maximum_construction_callback": _summary(
            [sample[3] for sample in measured]
        ),
        "topology": topology,
    }
    ObjectStateRegistry.clear()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=4.0)
    args = parser.parse_args()
    if args.iterations < 1 or args.warmups < 0:
        parser.error("iterations must be positive and warmups non-negative")
    print(
        json.dumps(
            run(
                iterations=args.iterations,
                warmups=args.warmups,
                timeout_s=args.timeout_seconds,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
