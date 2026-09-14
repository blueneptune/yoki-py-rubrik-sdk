"""`configure_logging()` is the only place in this SDK that touches
loguru's global sink list - everything else just emits log records through
whatever `logger` an `RscClient` was constructed with (see `client.py`).
These tests always remove the sink they add (`logger.remove(sink_id)`),
since loguru's `logger` is a process-wide singleton and a leftover sink
would otherwise leak into every later test's output.
"""

from __future__ import annotations

import io

from loguru import logger

from rubrik_rsc import RscClient, configure_logging


def test_configure_logging_captures_this_packages_log_lines() -> None:
    stream = io.StringIO()
    sink_id = configure_logging(stream, level="DEBUG")
    try:
        client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
        client.close()
    finally:
        logger.remove(sink_id)

    output = stream.getvalue()
    assert "Initialized RscClient" in output
    assert "Closing RscClient" in output


def test_configure_logging_defaults_to_filtering_out_other_packages() -> None:
    stream = io.StringIO()
    sink_id = configure_logging(stream, level="DEBUG")
    try:
        logger.debug("a message from somewhere else entirely")
    finally:
        logger.remove(sink_id)

    assert stream.getvalue() == ""


def test_configure_logging_with_only_this_package_false_captures_everything() -> None:
    stream = io.StringIO()
    sink_id = configure_logging(stream, level="DEBUG", only_this_package=False)
    try:
        logger.debug("a message from somewhere else entirely")
    finally:
        logger.remove(sink_id)

    assert "a message from somewhere else entirely" in stream.getvalue()


def test_configure_logging_returns_a_removable_sink_id() -> None:
    stream = io.StringIO()
    sink_id = configure_logging(stream, level="DEBUG")

    logger.remove(sink_id)
    RscClient("https://test-instance.my.rubrik.com", token="test-token")

    assert stream.getvalue() == ""
