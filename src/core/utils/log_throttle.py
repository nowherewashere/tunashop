"""Collapsing of repeated log lines on attacker-reachable rejection paths.

Public webhook endpoints answer junk with a rejection, and each rejection used to
write its own log line. That hands an attacker a write amplifier: a flood of
unauthenticated POSTs turns into unbounded disk I/O and buries genuine events
under noise, so the logs are least usable exactly when they matter most.

Callers still report every occurrence; this emits at most one line per interval
per key and folds the rest into a suppressed count, which keeps the signal (an
attack is visible, and its volume is reported) without the volume.
"""

from time import monotonic

from loguru import logger

# Keys are meant to be low-cardinality (a gateway name, a failure kind) — never
# attacker-controlled values such as an IP, which would make this map grow the way
# the log lines used to. The cap is a safety net for that mistake, not a design.
_MAX_TRACKED_KEYS = 256


class LogThrottle:
    """One emitted line per ``interval_seconds`` per key, with a suppressed count.

    Not thread-safe by design: it is only touched from the asyncio event loop.
    """

    def __init__(self, interval_seconds: float = 60.0) -> None:
        self.interval_seconds = interval_seconds
        self._last_emit: dict[str, float] = {}
        self._suppressed: dict[str, int] = {}

    def should_log(self, key: str) -> tuple[bool, int]:
        """Return ``(emit_now, suppressed_since_last_emit)``.

        When ``emit_now`` is False the event was folded into a later line; when it
        is True the count tells the caller how many occurrences it stands for.
        """
        now = monotonic()
        last = self._last_emit.get(key)

        if last is not None and now - last < self.interval_seconds:
            self._suppressed[key] = self._suppressed.get(key, 0) + 1
            return False, 0

        if last is None and len(self._last_emit) >= _MAX_TRACKED_KEYS:
            # Unexpected key explosion: drop the history rather than grow forever.
            # Worst case is a few extra lines while the map refills.
            self._last_emit.clear()
            self._suppressed.clear()

        self._last_emit[key] = now
        return True, self._suppressed.pop(key, 0)


def suppressed_suffix(suppressed: int) -> str:
    """`` (+N similar suppressed)`` for appending to a throttled message, else ``""``."""
    return f" (+{suppressed} similar suppressed)" if suppressed else ""


def log_throttled(
    throttle: LogThrottle,
    key: str,
    level: str,
    message: str,
    *,
    exception: bool = False,
) -> None:
    """Log ``message`` at ``level`` unless this key is inside its suppression window.

    Emits (and does nothing else) so call sites stay a single statement — returning a
    line for the caller to test would put a branch on every rejection path.

    ``level`` is a loguru level name ("WARNING", "CRITICAL", ...). Set ``exception``
    to attach the active traceback, as ``logger.exception`` would.
    """
    emit, suppressed = throttle.should_log(key)
    if not emit:
        return
    logger.opt(exception=exception).log(level, f"{message}{suppressed_suffix(suppressed)}")
