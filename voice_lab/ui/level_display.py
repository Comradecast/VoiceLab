from dataclasses import dataclass


DISPLAY_FLOOR_DBFS = -60.0
DISPLAY_CEILING_DBFS = 0.0
PEAK_HOLD_SECONDS = 0.8
OVERLOAD_LATCH_SECONDS = 1.8
SIGNAL_ABSENCE_SECONDS = 1.5
STALE_AFTER_SECONDS = 0.75


@dataclass(frozen=True)
class LevelDisplayState:
    bar_percent: int
    peak_percent: int
    level_text: str
    state_text: str
    overload_active: bool


class LevelDisplayModel:
    def __init__(self):
        self._bar_percent = 0.0
        self._peak_percent = 0.0
        self._peak_hold_until = 0.0
        self._overload_until = 0.0
        self._last_signal_at = None

    def update(self, reading, *, processing_state, captured_at, now):
        if processing_state != "running":
            self._reset()
            return LevelDisplayState(0, 0, "< -60 dB", "Stopped", False)
        if reading is None or captured_at is None:
            self._decay()
            return LevelDisplayState(
                int(round(self._bar_percent)),
                int(round(self._peak_percent)),
                "< -60 dB",
                "Waiting for signal",
                False,
            )
        if now - captured_at > STALE_AFTER_SECONDS:
            self._decay()
            return LevelDisplayState(
                int(round(self._bar_percent)),
                int(round(self._peak_percent)),
                _format_db(reading.peak_dbfs),
                "Meter update stale",
                False,
            )

        target = db_to_percent(reading.rms_dbfs)
        if target >= self._bar_percent:
            self._bar_percent = target
        else:
            self._bar_percent = max(0.0, self._bar_percent - 12.0)

        peak_target = db_to_percent(reading.peak_dbfs)
        if peak_target >= self._peak_percent:
            self._peak_percent = peak_target
            self._peak_hold_until = now + PEAK_HOLD_SECONDS
        elif now > self._peak_hold_until:
            self._peak_percent = max(peak_target, self._peak_percent - 8.0)

        if reading.overloaded:
            self._overload_until = now + OVERLOAD_LATCH_SECONDS
        overload_active = now < self._overload_until

        if reading.signal_present:
            self._last_signal_at = now
            state_text = "Signal active"
        elif self._last_signal_at is None:
            state_text = "Waiting for signal"
        elif now - self._last_signal_at >= SIGNAL_ABSENCE_SECONDS:
            state_text = "No signal detected"
        else:
            state_text = "Signal quiet"

        return LevelDisplayState(
            int(round(self._bar_percent)),
            int(round(self._peak_percent)),
            _format_db(reading.peak_dbfs),
            "Overload" if overload_active else state_text,
            overload_active,
        )

    def _reset(self):
        self._bar_percent = 0.0
        self._peak_percent = 0.0
        self._peak_hold_until = 0.0
        self._overload_until = 0.0
        self._last_signal_at = None

    def _decay(self):
        self._bar_percent = max(0.0, self._bar_percent - 12.0)
        self._peak_percent = max(0.0, self._peak_percent - 8.0)


def db_to_percent(dbfs):
    value = max(DISPLAY_FLOOR_DBFS, min(DISPLAY_CEILING_DBFS, float(dbfs)))
    return int(round(((value - DISPLAY_FLOOR_DBFS) / abs(DISPLAY_FLOOR_DBFS)) * 100.0))


def _format_db(dbfs):
    value = max(DISPLAY_FLOOR_DBFS, min(DISPLAY_CEILING_DBFS, float(dbfs)))
    if value <= DISPLAY_FLOOR_DBFS:
        return "< -60 dB"
    return f"{int(round(value))} dB"
