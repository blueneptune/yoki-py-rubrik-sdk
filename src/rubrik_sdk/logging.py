"""Optional convenience for configuring loguru output.

`RscClient` never calls `logger.add(...)` itself, and nothing in this
package does either - loguru's `logger` is a process-wide singleton, so a
library adding a sink on its own would silently mutate the *whole
application's* logging setup, and worse, would add another duplicate sink
every time another `RscClient` gets constructed (this SDK explicitly
supports running several side by side - see
`test_facade.py::test_two_rsc_instances_stay_isolated_to_their_own_client`).
Deciding where log records go is the application's job, not a dependency's -
see `RscClient.__init__`'s `logger` parameter for how you plug your own
loguru configuration in.

`configure_logging()` exists for the common case where you don't already
have loguru set up and just want this SDK's log lines to go somewhere
readable. It's a thin, explicit wrapper around one `logger.add()` call - not
something any other code in this package calls for you. Call it once,
yourself, before constructing any `RscClient`s.
"""

from __future__ import annotations

import sys
from typing import TextIO

from loguru import logger

_PACKAGE_NAME = __name__.rsplit(".", 1)[0]


def configure_logging(
    sink: TextIO = sys.stderr,
    *,
    level: str = "INFO",
    only_this_package: bool = True,
) -> int:
    """Add a sink for this SDK's log output.

    Returns the sink id `loguru.logger.add()` gives back - pass it to
    `loguru.logger.remove(sink_id)` later if you need to undo this (e.g. in
    tests, so one test's sink doesn't leak into the next).

    `only_this_package=True` (the default) scopes the sink to log records
    that originated in `rubrik_sdk` via loguru's `filter=` - if you already
    use loguru elsewhere in your application and want one sink to show
    everything, pass `only_this_package=False` instead of calling this at
    all and just call `loguru.logger.add()` yourself.
    """
    return logger.add(sink, level=level, filter=_PACKAGE_NAME if only_this_package else None)
