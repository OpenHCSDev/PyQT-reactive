"""Status presentation remains visual instead of amplifying polling logs."""

import logging

from pyqt_reactive.widgets.status_indicator import StatusIndicator, StatusState


def test_status_presentation_does_not_log_polling_updates(qapp, caplog) -> None:
    caplog.set_level(logging.INFO, logger="pyqt_reactive.widgets.status_indicator")
    indicator = StatusIndicator(show_refresh=False)

    try:
        indicator.set_state(StatusState.CONNECTED, "ZMQ: Connected")
        indicator.set_state(StatusState.CONNECTED, "ZMQ: Connected")

        assert indicator._label.text() == "ZMQ: Connected"
        assert caplog.records == []
    finally:
        indicator.close()
