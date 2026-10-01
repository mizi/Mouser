"""
core/scroll_engine.py — platform-free software scroll engine.

Turns a discrete wheel tick into a frame-paced stroke of pixel deltas, so one
detent glides instead of jumping and the glide is tunable (duration, brake
point, speed, acceleration, smoothing) in software, independently of what the
device firmware does.

Nothing here imports Qt, HID++ or any OS module. The platform hooks own two
edges only:

    hook  --push_tick(axis, direction, magnitude, now, modifiers)-->  engine
    hook  <--next_frame(now) -> (dy_px, dx_px)--                      engine

which keeps the whole physics model unit-testable with an explicit clock, and
keeps the three hooks from growing three subtly different curves.

The curve
---------
One tick schedules ``duration`` frames of motion. Speed is flat at ``peak``
until the brake point, then falls linearly to zero at the end of the stroke::

    D = max(2, duration);  B = max(1, min(brake_point, D));  peak = speed / 2
    w(f) = 0                    f >= D
         = 1                    f < B, or B >= D
         = (D - f) / (D - B)    otherwise

``B >= D`` is reachable from the UI (drag duration to 2 and brake to 2), and
without that guard it is a 0/0. The distance one tick travels is the *discrete*
sum over frames, not the area under the continuous ramp: at the defaults
(speed 10, D 12, B 4) that is 42.5 px, against 40.0 for the integral.
``total_distance_continuous`` is exposed for reference but never used to drive
anything.

Superposition
-------------
Ticks are summed into a fixed ring of per-frame deltas rather than kept as a
list of live animations. Adding a tick is O(D), advancing a frame is O(1)
regardless of how many are in flight, memory is fixed, and no objects are
allocated during a free spin. Because the sum is signed, reversing direction
mid-glide cancels the remaining distance instead of queueing behind it.

Why ``push_tick`` does almost nothing
-------------------------------------
It is called from inside the Windows low-level mouse hook, which has a ~300 ms
watchdog and sees ~3000 events/s during a SmartShift free spin. Everything it
does is arithmetic on a handful of floats plus a bounded ring write; there is
no lock, no allocation, and no I/O on that path.
"""

import math
import threading
import time

__all__ = [
    "AXIS_H",
    "AXIS_V",
    "FRAME_INTERVAL_S",
    "MOD_ALT",
    "MOD_CMD",
    "MOD_CTRL",
    "MOD_FAST",
    "MOD_HSCROLL",
    "MOD_NONE",
    "MOD_PASSTHROUGH",
    "MOD_SHIFT",
    "MOD_ZOOM",
    "SCROLL_TUNING_DEFAULTS",
    "SCROLL_TUNING_RANGES",
    "ScrollConfig",
    "ScrollCurve",
    "ScrollDriver",
    "ScrollEngine",
    "SubPixelAccumulator",
    "TickOutcome",
    "cumulative_profile",
    "curve_samples",
    "frame_profile",
    "frame_weight",
    "max_acceleration_gain",
    "resolve_mod_mode",
    "total_distance",
    "total_distance_continuous",
]

# ──────────────────────────────────────────────────────────────────────────────
# Tunable ranges — the single source of truth
#
# core/config.py imports these rather than restating them, so a slider bound,
# a migration default and the engine's own clamp cannot drift apart.
# ──────────────────────────────────────────────────────────────────────────────

SCROLL_TUNING_DEFAULTS = {
    "vscroll_duration": 12,
    "vscroll_brake_point": 4,
    "vscroll_speed": 10,
    "vscroll_acceleration": 7,
    "vscroll_smoothness": 0,
    "vscroll_smooth": False,
    "hscroll_speed": 5,
    "mod_scroll_shift_hscroll": True,
    "mod_scroll_ctrl_zoom": False,
    "mod_scroll_cmd_fast": False,
    "mod_scroll_invert_hscroll": False,
    "mod_scroll_invert_zoom": False,
    # Float literal on purpose: config's type validator tolerates an int where
    # a float default is declared, but not the reverse, so an int default here
    # would silently reset every user's fractional gain on load.
    "mod_scroll_gain": 3.2,
}

SCROLL_TUNING_RANGES = {
    "vscroll_duration": (2, 60),
    "vscroll_brake_point": (1, 12),
    "vscroll_speed": (1, 50),
    "vscroll_acceleration": (0, 60),
    "vscroll_smoothness": (0, 5),
    "hscroll_speed": (1, 50),
    "mod_scroll_gain": (0.1, 10.0),
}

AXIS_V = "v"
AXIS_H = "h"

FRAME_INTERVAL_S = 1.0 / 60.0

# Ring length. Must exceed twice the longest stroke (duration max 60) so a
# push can never wrap onto frames that have not been consumed yet.
RING_SIZE = 128

# The horizontal axis has no duration/brake/acceleration controls of its own.
# It still runs through the animator: a smooth vertical glide next to a stepped
# horizontal jump in the same view is the most obvious artefact of a half-done
# smooth-scroll tool, and the Shift-to-horizontal path needs an animator anyway.
H_DURATION_FRAMES = 8
H_BRAKE_FRAME = 3

# Acceleration. dt is the gap between whole ticks: at or below T_FAST the rate
# saturates at 1.0, at or above T_SLOW it is 0.0, and a gap longer than
# T_RESET is a new gesture rather than a slow one.
T_FAST = 0.030
T_SLOW = 0.200
T_RESET = 0.400
RATE_EMA_ALPHA = 0.5

# Squared rate: reading-speed scrolling stays near 1.0x and only a deliberate
# spin reaches the ceiling, which is 1 + acceleration/20 (4.0x at the maximum).
ACCEL_DIVISOR = 20.0

# A flywheel spin must stop within about one stroke of the wheel stopping,
# so refuse to schedule more than this much undelivered distance per axis.
MAX_INFLIGHT_PX = 6000.0

# An axis is done when its schedule is drained and the smoothing filter has
# decayed below half a tenth of a pixel.
IDLE_EPS = 0.02

# Bound on how long the smoothing tail may run past the end of the schedule.
# Purely a guard: a NaN that slipped into the filter would otherwise never
# fall below IDLE_EPS and the driver would spin forever.
def _max_tail_frames(smoothness):
    return 4 * (int(smoothness) + 1) + 2


# Ctrl+wheel zoom is quantized into whole steps by every app that implements
# it, so a gain of 10 must not fire 10 zoom steps for one detent forever.
MAX_ZOOM_REPEATS = 20

# Driver: how many frames may be emitted in one wake-up before the schedule is
# abandoned and re-based on the current time.
MAX_CATCHUP_FRAMES = 3

# Consecutive emit failures before the driver gives up rather than spinning.
MAX_CONSECUTIVE_ERRORS = 10

# Ten additions of 0.1 land a hair below 1.0 in binary floating point. Without
# a nudge every whole-unit crossing -- a delivered pixel, a counted detent --
# arrives one unit late, which reads as a lost pixel per stroke and as a
# hi-res burst that never completes a tick.
_UNIT_EPS = 1e-9

MOD_SHIFT = "shift"
MOD_CTRL = "ctrl"
MOD_CMD = "cmd"
# Reported so it can be passed through, never handled: Alt+wheel belongs to
# the application (it is Photoshop's cursor-anchored zoom).
MOD_ALT = "alt"
_KNOWN_MODS = frozenset({MOD_SHIFT, MOD_CTRL, MOD_CMD})

MOD_NONE = "none"
MOD_HSCROLL = "hscroll"
MOD_ZOOM = "zoom"
MOD_FAST = "fast"
MOD_PASSTHROUGH = "passthrough"


# ──────────────────────────────────────────────────────────────────────────────
# Curve
# ──────────────────────────────────────────────────────────────────────────────


def _clamp(value, low, high):
    return low if value < low else (high if value > high else value)


def _clamp_int(value, low, high, fallback):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return _clamp(number, low, high)


def _clamp_float(value, low, high, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):
        return fallback
    return _clamp(number, low, high)


def _duration_of(duration):
    return _clamp_int(duration, *SCROLL_TUNING_RANGES["vscroll_duration"],
                      fallback=SCROLL_TUNING_DEFAULTS["vscroll_duration"])


def _brake_of(brake_point, duration):
    brake = _clamp_int(brake_point, 1, RING_SIZE,
                       fallback=SCROLL_TUNING_DEFAULTS["vscroll_brake_point"])
    return max(1, min(brake, duration))


def frame_weight(frame, duration, brake_point):
    """Speed at ``frame`` as a fraction of the stroke's peak, in [0, 1]."""
    d = _duration_of(duration)
    b = _brake_of(brake_point, d)
    if frame < 0 or frame >= d:
        return 0.0
    # b >= d means the ramp has no room; the whole stroke is the plateau.
    # Reachable from the UI, and a 0/0 without this branch.
    if frame < b or b >= d:
        return 1.0
    return (d - frame) / (d - b)


def frame_profile(duration, brake_point, speed):
    """Per-frame pixel deltas for one tick, one entry per frame of the stroke."""
    d = _duration_of(duration)
    b = _brake_of(brake_point, d)
    peak = _clamp_float(speed, *SCROLL_TUNING_RANGES["vscroll_speed"],
                        fallback=SCROLL_TUNING_DEFAULTS["vscroll_speed"]) / 2.0
    return [peak * frame_weight(f, d, b) for f in range(d)]


def cumulative_profile(duration, brake_point, speed):
    """Running total of :func:`frame_profile`."""
    total = 0.0
    out = []
    for value in frame_profile(duration, brake_point, speed):
        total += value
        out.append(total)
    return out


def total_distance(duration, brake_point, speed):
    """Distance one tick actually travels: the discrete sum over frames."""
    return sum(frame_profile(duration, brake_point, speed))


def total_distance_continuous(duration, brake_point, speed):
    """Area under the continuous ramp. Reference only, never used to drive."""
    d = _duration_of(duration)
    b = _brake_of(brake_point, d)
    peak = _clamp_float(speed, *SCROLL_TUNING_RANGES["vscroll_speed"],
                        fallback=SCROLL_TUNING_DEFAULTS["vscroll_speed"]) / 2.0
    return peak * (b + (d - b) / 2.0)


def _smoothing_alpha(smoothness):
    m = _clamp_int(smoothness, *SCROLL_TUNING_RANGES["vscroll_smoothness"],
                   fallback=0)
    # alpha == 1.0 is not "almost no smoothing", it is the filter removed:
    # ema = raw exactly, so smoothing-off is bit-identical to the raw profile.
    return 1.0 if m <= 0 else 1.0 / (1.0 + m)


def _smooth_series(values, smoothness):
    alpha = _smoothing_alpha(smoothness)
    if alpha >= 1.0:
        return list(values)
    ema = 0.0
    out = []
    for value in values:
        ema += alpha * (value - ema)
        out.append(ema)
    return out


def max_acceleration_gain(acceleration):
    """The ceiling the acceleration slider can reach (rate saturated at 1.0)."""
    a = _clamp_float(acceleration, *SCROLL_TUNING_RANGES["vscroll_acceleration"],
                     fallback=0)
    return 1.0 + a / ACCEL_DIVISOR


def curve_samples(duration, brake_point, speed, acceleration=0, smoothness=0):
    """Samples for the settings-page graph.

    One dict per frame: ``frame``, ``speed`` (px this frame, after smoothing),
    ``total`` (cumulative px) and ``boosted`` (``speed`` at the acceleration
    ceiling). The series runs one frame past the stroke so the curve is drawn
    returning to zero, plus the smoothing tail when there is one, so the
    cumulative line still ends at the real total distance.

    This is the same code the injector runs, exposed to QML through the
    backend, so the graph cannot quietly disagree with the mouse.
    """
    d = _duration_of(duration)
    tail = 0 if _smoothing_alpha(smoothness) >= 1.0 else _max_tail_frames(smoothness)
    raw = frame_profile(d, brake_point, speed) + [0.0] * (1 + tail)
    series = _smooth_series(raw, smoothness)
    gain = max_acceleration_gain(acceleration)
    out = []
    total = 0.0
    for index, value in enumerate(series):
        total += value
        out.append({
            "frame": index,
            "speed": value,
            "total": total,
            "boosted": value * gain,
        })
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────


class ScrollCurve:
    """Immutable stroke shape: how long, when to brake, how fast."""

    __slots__ = ("duration", "brake_point", "speed")

    def __init__(self, duration=12, brake_point=4, speed=10):
        d = _duration_of(duration)
        object.__setattr__(self, "duration", d)
        object.__setattr__(self, "brake_point", _brake_of(brake_point, d))
        object.__setattr__(
            self, "speed",
            _clamp_int(speed, *SCROLL_TUNING_RANGES["vscroll_speed"],
                       fallback=SCROLL_TUNING_DEFAULTS["vscroll_speed"]),
        )

    def __setattr__(self, name, value):
        raise AttributeError("ScrollCurve is immutable")

    @property
    def peak(self):
        return self.speed / 2.0

    def profile(self):
        return frame_profile(self.duration, self.brake_point, self.speed)

    def total_distance(self):
        return total_distance(self.duration, self.brake_point, self.speed)

    def __eq__(self, other):
        if not isinstance(other, ScrollCurve):
            return NotImplemented
        return (self.duration, self.brake_point, self.speed) == (
            other.duration, other.brake_point, other.speed)

    def __hash__(self):
        return hash((self.duration, self.brake_point, self.speed))

    def __repr__(self):
        return (f"ScrollCurve(duration={self.duration}, "
                f"brake_point={self.brake_point}, speed={self.speed})")


class ScrollConfig:
    """Everything the engine needs, already clamped to its UI ranges.

    Construct it once per settings change and hand it to :meth:`ScrollEngine.configure`.
    """

    __slots__ = (
        "enabled", "v", "acceleration", "smoothness", "h_speed",
        "invert_v", "invert_h", "mod_shift_hscroll", "mod_ctrl_zoom",
        "mod_cmd_fast", "mod_gain", "invert_mod_h", "invert_zoom",
        "frame_interval_s",
    )

    def __init__(self, enabled=False, v=None, acceleration=7, smoothness=0,
                 h_speed=5, invert_v=False, invert_h=False,
                 mod_shift_hscroll=True, mod_ctrl_zoom=False,
                 mod_cmd_fast=False, mod_gain=3.2, invert_mod_h=False,
                 invert_zoom=False, frame_interval_s=FRAME_INTERVAL_S):
        set_ = object.__setattr__
        set_(self, "enabled", bool(enabled))
        set_(self, "v", v if isinstance(v, ScrollCurve) else ScrollCurve())
        set_(self, "acceleration",
             _clamp_int(acceleration, *SCROLL_TUNING_RANGES["vscroll_acceleration"],
                        fallback=SCROLL_TUNING_DEFAULTS["vscroll_acceleration"]))
        set_(self, "smoothness",
             _clamp_int(smoothness, *SCROLL_TUNING_RANGES["vscroll_smoothness"],
                        fallback=0))
        set_(self, "h_speed",
             _clamp_int(h_speed, *SCROLL_TUNING_RANGES["hscroll_speed"],
                        fallback=SCROLL_TUNING_DEFAULTS["hscroll_speed"]))
        set_(self, "invert_v", bool(invert_v))
        set_(self, "invert_h", bool(invert_h))
        set_(self, "mod_shift_hscroll", bool(mod_shift_hscroll))
        set_(self, "mod_ctrl_zoom", bool(mod_ctrl_zoom))
        set_(self, "mod_cmd_fast", bool(mod_cmd_fast))
        set_(self, "mod_gain",
             _clamp_float(mod_gain, *SCROLL_TUNING_RANGES["mod_scroll_gain"],
                          fallback=SCROLL_TUNING_DEFAULTS["mod_scroll_gain"]))
        set_(self, "invert_mod_h", bool(invert_mod_h))
        set_(self, "invert_zoom", bool(invert_zoom))
        set_(self, "frame_interval_s",
             _clamp_float(frame_interval_s, 1.0 / 480.0, 1.0,
                          fallback=FRAME_INTERVAL_S))

    def __setattr__(self, name, value):
        raise AttributeError("ScrollConfig is immutable")

    @property
    def h_curve(self):
        return ScrollCurve(H_DURATION_FRAMES, H_BRAKE_FRAME, self.h_speed)

    def normalized(self):
        """Already clamped at construction; here so callers can be explicit."""
        return self

    @classmethod
    def from_settings(cls, settings, *, native_invert_active=False):
        """Build from a ``config["settings"]`` dict.

        ``native_invert_active`` is the only thing the engine ever hears about
        HID++: when the firmware is already flipping the wheel, the software
        path must not flip it a second time.
        """
        get = (settings or {}).get
        return cls(
            enabled=get("vscroll_smooth", False),
            v=ScrollCurve(
                duration=get("vscroll_duration", 12),
                brake_point=get("vscroll_brake_point", 4),
                speed=get("vscroll_speed", 10),
            ),
            acceleration=get("vscroll_acceleration", 7),
            smoothness=get("vscroll_smoothness", 0),
            h_speed=get("hscroll_speed", 5),
            invert_v=bool(get("invert_vscroll", False)) and not native_invert_active,
            invert_h=bool(get("invert_hscroll", False)) and not native_invert_active,
            mod_shift_hscroll=get("mod_scroll_shift_hscroll", True),
            mod_ctrl_zoom=get("mod_scroll_ctrl_zoom", False),
            mod_cmd_fast=get("mod_scroll_cmd_fast", False),
            mod_gain=get("mod_scroll_gain", 3.2),
            invert_mod_h=get("mod_scroll_invert_hscroll", False),
            invert_zoom=get("mod_scroll_invert_zoom", False),
        )

    def __eq__(self, other):
        if not isinstance(other, ScrollConfig):
            return NotImplemented
        return all(getattr(self, name) == getattr(other, name)
                   for name in self.__slots__)

    def __repr__(self):
        fields = ", ".join(f"{name}={getattr(self, name)!r}"
                           for name in self.__slots__)
        return f"ScrollConfig({fields})"


def resolve_mod_mode(modifiers, config):
    """Which behaviour a wheel tick gets, given the modifiers held.

    Anything other than exactly one handled modifier is the application's, and
    passes through untouched -- not animated, not rewritten:

    - two or more held, whether or not each is switched on. Gating on the
      enabled ones alone turns Ctrl+Shift+wheel into a horizontal pan whenever
      Ctrl-zoom is off, and that combination is an app's to bind.
    - any modifier Mouser does not handle, alone or combined. Smooth scroll
      would otherwise swallow Alt+wheel and replay it as a plain glide, and
      Photoshop's Alt+wheel zoom would never see its event.
    """
    held = frozenset(modifiers or ())
    if not held:
        return MOD_NONE
    if len(held) >= 2 or not held <= _KNOWN_MODS:
        return MOD_PASSTHROUGH
    mod = next(iter(held))
    if mod == MOD_CTRL:
        return MOD_ZOOM if config.mod_ctrl_zoom else MOD_NONE
    if mod == MOD_SHIFT:
        return MOD_HSCROLL if config.mod_shift_hscroll else MOD_NONE
    return MOD_FAST if config.mod_cmd_fast else MOD_NONE


class TickOutcome:
    """What the hook should do with the wheel event it just handed over.

    ``swallow``             block the original event.
    ``passthrough_repeats`` emit this many discrete wheel events instead.
    ``passthrough_direction`` sign for those events (zoom inversion applied).
    """

    __slots__ = ("swallow", "passthrough_repeats", "passthrough_direction")

    def __init__(self, swallow=False, passthrough_repeats=0,
                 passthrough_direction=1):
        object.__setattr__(self, "swallow", bool(swallow))
        object.__setattr__(self, "passthrough_repeats", int(passthrough_repeats))
        object.__setattr__(self, "passthrough_direction",
                           1 if passthrough_direction >= 0 else -1)

    def __setattr__(self, name, value):
        raise AttributeError("TickOutcome is immutable")

    def __eq__(self, other):
        if not isinstance(other, TickOutcome):
            return NotImplemented
        return all(getattr(self, n) == getattr(other, n) for n in self.__slots__)

    def __repr__(self):
        return (f"TickOutcome(swallow={self.swallow}, "
                f"passthrough_repeats={self.passthrough_repeats}, "
                f"passthrough_direction={self.passthrough_direction})")


# ──────────────────────────────────────────────────────────────────────────────
# Sub-pixel carry
# ──────────────────────────────────────────────────────────────────────────────


class SubPixelAccumulator:
    """Turns a stream of fractional amounts into whole units, losing nothing.

    Truncation toward zero (not floor) keeps the carried remainder on the same
    side of zero as the motion, so a run of positive values followed by a run
    of negative ones cannot leak a spurious unit at the reversal.
    """

    __slots__ = ("_residue",)

    def __init__(self):
        self._residue = 0.0

    def take(self, value):
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return 0
        if not math.isfinite(amount):
            self.reset()
            return 0
        self._residue += amount
        whole = math.trunc(self._residue
                           + math.copysign(_UNIT_EPS, self._residue))
        self._residue -= whole
        return int(whole)

    @property
    def residue(self):
        return self._residue

    def reset(self):
        self._residue = 0.0


# ──────────────────────────────────────────────────────────────────────────────
# One animated axis
# ──────────────────────────────────────────────────────────────────────────────


class _Axis:
    """Ring of scheduled per-frame deltas, plus this axis's tick-rate state."""

    def __init__(self, size=RING_SIZE):
        self._size = size
        self._sched = [0.0] * size
        self._cursor = 0
        self._horizon = 0
        self._pending = 0.0
        self._ema = 0.0
        self._tail = 0
        self._accum = SubPixelAccumulator()
        self._rate = 0.0
        self._accum_ticks = 0.0
        self._last_whole_tick_at = None

    # ── scheduling ────────────────────────────────────────────────────────

    def push(self, direction, magnitude, curve, gain):
        """Superpose one tick's stroke onto the schedule."""
        if abs(self._pending) >= MAX_INFLIGHT_PX:
            return 0.0
        amount = curve.peak * gain * magnitude * (1 if direction >= 0 else -1)
        if amount == 0.0 or not math.isfinite(amount):
            return 0.0
        duration = curve.duration
        brake = curve.brake_point
        total = 0.0
        for frame in range(duration):
            value = amount * frame_weight(frame, duration, brake)
            self._sched[(self._cursor + frame) % self._size] += value
            total += value
        self._pending += total
        self._horizon = max(self._horizon, duration)
        return total

    def advance(self, smoothness):
        """Consume one frame. Returns the smoothed pixel delta for it."""
        index = self._cursor
        raw = self._sched[index]
        self._sched[index] = 0.0
        self._cursor = (index + 1) % self._size
        if self._horizon > 0:
            self._horizon -= 1
            self._tail = 0
        else:
            self._tail += 1
        self._pending -= raw

        alpha = _smoothing_alpha(smoothness)
        if alpha >= 1.0:
            self._ema = raw
        else:
            self._ema += alpha * (raw - self._ema)

        if not math.isfinite(self._ema):
            self.reset()
            return 0.0
        if self._horizon <= 0 and self._tail > _max_tail_frames(smoothness):
            self._ema = 0.0
        return self._ema

    def take_whole(self, value):
        return self._accum.take(value)

    def is_idle(self, smoothness):
        if self._horizon > 0:
            return False
        if abs(self._ema) >= IDLE_EPS:
            return False
        return abs(self._accum.residue) < 1.0

    def flush(self):
        """Emit whatever whole pixels the carry still holds, then clear it."""
        residue = self._accum.residue
        self._accum.reset()
        return int(math.trunc(residue))

    def reset(self):
        for index in range(self._size):
            self._sched[index] = 0.0
        self._cursor = 0
        self._horizon = 0
        self._pending = 0.0
        self._ema = 0.0
        self._tail = 0
        self._accum.reset()
        self._rate = 0.0
        self._accum_ticks = 0.0
        self._last_whole_tick_at = None

    # ── acceleration ──────────────────────────────────────────────────────

    def note_tick(self, magnitude, now, acceleration):
        """Fold one tick into the rate estimate and return this tick's gain.

        The rate is sampled per *whole* tick, never per event. A hi-res wheel
        emits roughly fifteen messages per detent about a millisecond apart;
        timing those directly reads as a 1000 Hz scroll and hands maximum boost
        to every single detent.
        """
        self._accum_ticks += magnitude
        while self._accum_ticks >= 1.0 - _UNIT_EPS:
            self._accum_ticks -= 1.0
            self._sample_rate(now)
        return self.gain(acceleration)

    def _sample_rate(self, now):
        last = self._last_whole_tick_at
        self._last_whole_tick_at = now
        if last is None:
            self._rate = 0.0
            return
        dt = now - last
        if not math.isfinite(dt) or dt > T_RESET:
            self._rate = 0.0
            return
        target = _clamp((T_SLOW - dt) / (T_SLOW - T_FAST), 0.0, 1.0)
        self._rate += RATE_EMA_ALPHA * (target - self._rate)

    def gain(self, acceleration):
        # acceleration 0 must be an exact no-op, not "very nearly 1.0".
        if acceleration <= 0:
            return 1.0
        return 1.0 + (acceleration / ACCEL_DIVISOR) * (self._rate ** 2)

    @property
    def rate(self):
        return self._rate


# ──────────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────────


class ScrollEngine:
    """Wheel ticks in, per-frame pixel deltas out."""

    def __init__(self, config=None):
        self._cfg = config if isinstance(config, ScrollConfig) else ScrollConfig()
        self._v = _Axis()
        self._h = _Axis()
        self._zoom_accum = SubPixelAccumulator()
        self._zoom_ticks = 0.0

    # ── configuration ─────────────────────────────────────────────────────

    @property
    def config(self):
        return self._cfg

    def configure(self, config):
        """Swap the tuning. Anything already in flight keeps its old shape."""
        new = config if isinstance(config, ScrollConfig) else ScrollConfig()
        was_enabled = self._cfg.enabled
        self._cfg = new
        if was_enabled and not new.enabled:
            self.reset()

    # ── input ─────────────────────────────────────────────────────────────

    def push_tick(self, axis, direction, magnitude, now=None,
                  modifiers=frozenset()):
        """Feed one wheel event. Cheap enough for a low-level hook proc.

        ``magnitude`` is in whole detents: a hi-res sub-step of 8/120 passes
        8/120, and the ring superposes the burst back into exactly one detent.
        """
        cfg = self._cfg
        if not cfg.enabled:
            return TickOutcome()
        try:
            amount = abs(float(magnitude))
        except (TypeError, ValueError):
            return TickOutcome()
        if not math.isfinite(amount) or amount <= 0.0:
            return TickOutcome()
        sign = 1 if direction >= 0 else -1
        when = time.monotonic() if now is None else now

        if axis == AXIS_H:
            flip = -1 if cfg.invert_h else 1
            self._h.push(sign * flip, amount, cfg.h_curve, 1.0)
            return TickOutcome(swallow=True)

        mode = resolve_mod_mode(modifiers, cfg)
        if mode == MOD_PASSTHROUGH:
            return TickOutcome()
        if mode == MOD_ZOOM:
            return self._zoom_outcome(sign, amount, cfg)

        self._zoom_ticks = 0.0
        if mode == MOD_HSCROLL:
            flip = -1 if cfg.invert_mod_h else 1
            self._h.push(sign * flip, amount, cfg.h_curve, 1.0)
            return TickOutcome(swallow=True)

        gain = self._v.note_tick(amount, when, cfg.acceleration)
        if mode == MOD_FAST:
            gain *= cfg.mod_gain
        flip = -1 if cfg.invert_v else 1
        self._v.push(sign * flip, amount, cfg.v, gain)
        return TickOutcome(swallow=True)

    def _zoom_outcome(self, sign, amount, cfg):
        """Ctrl+wheel: quantized discrete steps, the animator bypassed entirely.

        Every application turns zoom into steps, so 60 sub-pixel events a
        second either do nothing at all or zoom wildly. The gain is carried
        across detents instead, so 3.2 comes out as 3, 3, 3, 3, 4.
        """
        self._zoom_ticks += amount
        whole = 0
        while self._zoom_ticks >= 1.0 - _UNIT_EPS:
            self._zoom_ticks -= 1.0
            whole += 1
        if whole == 0:
            # A sub-detent fragment of a hi-res burst. Swallow it so the burst
            # does not also arrive unscaled; the whole tick will fire shortly.
            return TickOutcome(swallow=True)
        repeats = 0
        for _ in range(whole):
            repeats += max(1, self._zoom_accum.take(cfg.mod_gain))
        repeats = min(repeats, MAX_ZOOM_REPEATS)
        out_sign = -sign if cfg.invert_zoom else sign
        if repeats == 1 and out_sign == sign:
            # Identical to the event we were given; let the original through
            # rather than blocking it and posting a copy.
            return TickOutcome()
        return TickOutcome(swallow=True, passthrough_repeats=repeats,
                           passthrough_direction=out_sign)

    # ── output ────────────────────────────────────────────────────────────

    def next_frame(self, now=None):
        """Pixels to inject for one frame, or ``None`` when there is nothing.

        ``None`` is the signal to stop the frame loop: an idle engine must
        cost nothing at all.
        """
        smoothness = self._cfg.smoothness
        if self._v.is_idle(smoothness) and self._h.is_idle(smoothness):
            return None
        dy = self._v.take_whole(self._v.advance(smoothness))
        dx = self._h.take_whole(self._h.advance(smoothness))
        return (dy, dx)

    @property
    def idle(self):
        smoothness = self._cfg.smoothness
        return self._v.is_idle(smoothness) and self._h.is_idle(smoothness)

    def flush(self):
        """Drop everything scheduled but emit the sub-pixel carry first."""
        dy = self._v.flush()
        dx = self._h.flush()
        self.reset()
        return (dy, dx)

    def reset(self):
        self._v.reset()
        self._h.reset()
        self._zoom_accum.reset()
        self._zoom_ticks = 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Frame loop
# ──────────────────────────────────────────────────────────────────────────────


class _NullWrapper:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _null_wrapper():
    return _NullWrapper()


class ScrollDriver:
    """Runs :meth:`ScrollEngine.next_frame` on a frame clock and emits the result.

    The thread blocks on an event whenever the engine is idle, so a session
    where nobody scrolls costs nothing. ``wake()`` is what a hook calls after
    ``push_tick``.

    ``frame_wrapper`` is entered once per frame, not once per loop: on macOS it
    is ``objc.autorelease_pool``, and a pool held open across the whole loop
    never drains, so every autoreleased object from every frame of a glide
    piles up until the loop exits.
    """

    def __init__(self, engine, emit, *, frame_interval_s=None,
                 frame_wrapper=None, clock=None, sleep=None,
                 name="MouseHook-scroll", idle_wait_s=0.25):
        self._engine = engine
        self._emit = emit
        self._interval = float(frame_interval_s or engine.config.frame_interval_s)
        self._frame_wrapper = frame_wrapper or _null_wrapper
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._name = name
        self._idle_wait = idle_wait_s
        self._thread = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._next_frame_at = None
        self._errors = 0

    # ── lifecycle ─────────────────────────────────────────────────────────

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self._errors = 0
        self._next_frame_at = None
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=self._name)
        self._thread.start()

    def stop(self, flush=False, timeout=1.0):
        self._stop.set()
        self._wake.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        if flush:
            dy, dx = self._engine.flush()
            if dy or dx:
                self._deliver(dy, dx)
        else:
            self._engine.reset()

    def wake(self):
        self._wake.set()

    # ── loop ──────────────────────────────────────────────────────────────

    def _run(self):
        while not self._stop.is_set():
            if self._engine.idle:
                self._next_frame_at = None
                self._wake.clear()
                if self._engine.idle:
                    self._wake.wait(self._idle_wait)
                continue
            now = self._clock()
            if self._next_frame_at is None:
                self._next_frame_at = now
            delay = self._next_frame_at - now
            if delay > 0:
                self._sleep(min(delay, self._interval))
                continue
            if not self._run_once(self._clock()):
                break

    def _run_once(self, now):
        """Advance the engine up to ``now``. Returns False to stop the loop.

        A late wake-up replays at most MAX_CATCHUP_FRAMES frames; anything
        further behind (the machine slept, the thread was starved) is not worth
        replaying at all, so the schedule is re-based on the current time and
        one frame is emitted. Replaying a backlog would land the whole glide in
        a single visible jump.
        """
        if self._next_frame_at is None:
            self._next_frame_at = now
        behind = now - self._next_frame_at
        frames = int(behind / self._interval) + 1 if behind >= 0 else 1
        if frames > MAX_CATCHUP_FRAMES:
            frames = 1
            self._next_frame_at = now
        for _ in range(frames):
            if not self._emit_frame():
                return False
            if self._next_frame_at is None:
                # The engine went idle mid-catch-up; there is nothing left
                # to pace, and the loop will block until the next push.
                return True
            self._next_frame_at += self._interval
        return True

    def _emit_frame(self):
        try:
            with self._frame_wrapper():
                frame = self._engine.next_frame()
                if frame is None:
                    self._next_frame_at = None
                    return True
                dy, dx = frame
                if dy or dx:
                    self._emit(dy, dx)
        except Exception as exc:
            self._errors += 1
            if self._errors >= MAX_CONSECUTIVE_ERRORS:
                print(f"[ScrollDriver] stopping after {self._errors} "
                      f"consecutive errors: {exc}")
                return False
            return True
        self._errors = 0
        return True

    def _deliver(self, dy, dx):
        try:
            with self._frame_wrapper():
                self._emit(dy, dx)
        except Exception as exc:
            print(f"[ScrollDriver] flush failed: {exc}")
