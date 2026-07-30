"""Lifecycle regressions for the nominal Qt key-sequence editor."""

from pyqt_reactive.protocols import KeySequenceEditAdapter


def test_key_sequence_disconnect_preserves_unrelated_callback(qapp) -> None:
    widget = KeySequenceEditAdapter()
    first_values: list[str] = []
    second_values: list[str] = []

    def first_callback(value: str) -> None:
        first_values.append(value)

    def second_callback(value: str) -> None:
        second_values.append(value)

    widget.connect_change_signal(first_callback)
    widget.connect_change_signal(second_callback)
    widget.disconnect_change_signal(first_callback)
    widget.editingFinished.emit()

    assert first_values == []
    assert second_values == [""]


def test_key_sequence_duplicate_connect_is_idempotent(qapp) -> None:
    widget = KeySequenceEditAdapter()
    values: list[str] = []

    def callback(value: str) -> None:
        values.append(value)

    widget.connect_change_signal(callback)
    widget.connect_change_signal(callback)
    widget.editingFinished.emit()
    widget.disconnect_change_signal(callback)
    widget.editingFinished.emit()

    assert values == [""]
