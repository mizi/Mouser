"""
core/scroll_modifiers.py — modifier+wheel translation, shared by all three hooks.

Each platform reports held modifiers differently: macOS reads flags already
carried on the scroll event, Windows polls the key state, Linux reads the
keyboard devices it has open. This module takes the one thing they can all
produce -- a bitmask -- and answers the only question the hooks actually have:
what should this wheel event become?

The precedence rules live in :func:`core.scroll_engine.resolve_mod_mode`, so
the software engine (smooth scroll on) and the plain translation path (smooth
scroll off) cannot disagree about what Ctrl+Shift+wheel means.

Scaling runs through :class:`ScrollAccumulator` rather than plain rounding.
A gain of 3.2 applied to a hi-res delta of 8 is 25.6, and dropping that .6
every message is a 2% error that compounds across a burst.
"""

import math

from core.scroll_engine import (
    MOD_ALT as _ALT_NAME,
    MOD_CMD,
    MOD_CTRL,
    MOD_FAST,
    MOD_HSCROLL,
    MOD_NONE,
    MOD_PASSTHROUGH,
    MOD_SHIFT,
    MOD_ZOOM,
    SCROLL_TUNING_DEFAULTS,
    SCROLL_TUNING_RANGES,
    resolve_mod_mode,
)

__all__ = [
    "MOD_ALT",
    "MOD_CTRL_BIT",
    "MOD_META",
    "MOD_SHIFT_BIT",
    "ModScrollSettings",
    "ScrollAccumulator",
    "WheelPlan",
    "clamp_gain",
    "modifier_names",
    "resolve_wheel_action",
]

# Platform-neutral modifier bits. Every hook maps its own key codes onto these
# and nothing downstream needs to know which platform produced the mask.
MOD_SHIFT_BIT = 0x01
MOD_CTRL_BIT = 0x02
MOD_ALT = 0x04
# Command on macOS, Super/Windows key elsewhere.
MOD_META = 0x08

_BIT_NAMES = (
    (MOD_CTRL_BIT, MOD_CTRL),
    (MOD_SHIFT_BIT, MOD_SHIFT),
    (MOD_META, MOD_CMD),
    (MOD_ALT, _ALT_NAME),
)

_GAIN_LOW, _GAIN_HIGH = SCROLL_TUNING_RANGES["mod_scroll_gain"]
_GAIN_DEFAULT = SCROLL_TUNING_DEFAULTS["mod_scroll_gain"]

# Ten additions of 0.1 land a hair below 1.0 in binary floating point, which
# would hold a whole unit back a tick longer than it should.
_UNIT_EPS = 1e-9


def modifier_names(mask):
    """Bitmask to the modifier names the engine speaks.

    Alt is reported even though Mouser never acts on it: the engine has to know
    it is held to leave Alt+wheel alone instead of animating it.
    """
    try:
        bits = int(mask)
    except (TypeError, ValueError):
        return frozenset()
    return frozenset(name for bit, name in _BIT_NAMES if bits & bit)


def clamp_gain(value):
    """Force a stored gain into the slider's range.

    The value reaches here from a JSON file a user may have hand-edited, so
    every way of not being a number has to land on the default rather than
    propagate a NaN into a scroll delta.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _GAIN_DEFAULT
    if not math.isfinite(number):
        return _GAIN_DEFAULT
    return min(_GAIN_HIGH, max(_GAIN_LOW, number))


class ModScrollSettings:
    """The modifier-scroll half of ``config["settings"]``.

    Field names match :class:`core.scroll_engine.ScrollConfig` so both satisfy
    :func:`resolve_mod_mode` without an adapter.
    """

    __slots__ = (
        "mod_shift_hscroll", "mod_ctrl_zoom", "mod_cmd_fast",
        "invert_mod_h", "invert_zoom", "mod_gain",
    )

    def __init__(self, mod_shift_hscroll=True, mod_ctrl_zoom=False,
                 mod_cmd_fast=False, invert_mod_h=False, invert_zoom=False,
                 mod_gain=_GAIN_DEFAULT):
        set_ = object.__setattr__
        set_(self, "mod_shift_hscroll", bool(mod_shift_hscroll))
        set_(self, "mod_ctrl_zoom", bool(mod_ctrl_zoom))
        set_(self, "mod_cmd_fast", bool(mod_cmd_fast))
        set_(self, "invert_mod_h", bool(invert_mod_h))
        set_(self, "invert_zoom", bool(invert_zoom))
        set_(self, "mod_gain", clamp_gain(mod_gain))

    def __setattr__(self, name, value):
        raise AttributeError("ModScrollSettings is immutable")

    @classmethod
    def from_settings(cls, settings):
        get = (settings or {}).get
        return cls(
            mod_shift_hscroll=get("mod_scroll_shift_hscroll", True),
            mod_ctrl_zoom=get("mod_scroll_ctrl_zoom", False),
            mod_cmd_fast=get("mod_scroll_cmd_fast", False),
            invert_mod_h=get("mod_scroll_invert_hscroll", False),
            invert_zoom=get("mod_scroll_invert_zoom", False),
            mod_gain=get("mod_scroll_gain", _GAIN_DEFAULT),
        )

    def __eq__(self, other):
        if not isinstance(other, ModScrollSettings):
            return NotImplemented
        return all(getattr(self, n) == getattr(other, n) for n in self.__slots__)

    def __repr__(self):
        fields = ", ".join(f"{n}={getattr(self, n)!r}" for n in self.__slots__)
        return f"ModScrollSettings({fields})"


class WheelPlan:
    """What a hook should do with one wheel event.

    ``v_scale`` / ``h_scale``  multiply the raw vertical delta to produce the
                               vertical and horizontal output.
    ``strip_mods``             modifier bits to clear on the re-posted event.
    ``is_noop``                nothing to do; let the original through.
    """

    __slots__ = ("mode", "v_scale", "h_scale", "strip_mods", "is_noop")

    def __init__(self, mode=MOD_NONE, v_scale=1.0, h_scale=0.0, strip_mods=0,
                 is_noop=False):
        set_ = object.__setattr__
        set_(self, "mode", mode)
        set_(self, "v_scale", float(v_scale))
        set_(self, "h_scale", float(h_scale))
        set_(self, "strip_mods", int(strip_mods))
        set_(self, "is_noop", bool(is_noop))

    def __setattr__(self, name, value):
        raise AttributeError("WheelPlan is immutable")

    def __eq__(self, other):
        if not isinstance(other, WheelPlan):
            return NotImplemented
        return all(getattr(self, n) == getattr(other, n) for n in self.__slots__)

    def __repr__(self):
        fields = ", ".join(f"{n}={getattr(self, n)!r}" for n in self.__slots__)
        return f"WheelPlan({fields})"


_NOOP_PLAN = WheelPlan(mode=MOD_NONE, v_scale=1.0, h_scale=0.0, is_noop=True)
_PASSTHROUGH_PLAN = WheelPlan(mode=MOD_PASSTHROUGH, v_scale=1.0, h_scale=0.0,
                              is_noop=True)


def resolve_wheel_action(mask, settings):
    """Turn a modifier bitmask into a :class:`WheelPlan`."""
    mode = resolve_mod_mode(modifier_names(mask), settings)
    if mode == MOD_PASSTHROUGH:
        return _PASSTHROUGH_PLAN
    if mode == MOD_HSCROLL:
        # Shift is stripped: an app that translates Shift+wheel itself would
        # otherwise translate the horizontal event a second time.
        return WheelPlan(
            mode=MOD_HSCROLL,
            v_scale=0.0,
            h_scale=-1.0 if settings.invert_mod_h else 1.0,
            strip_mods=MOD_SHIFT_BIT,
        )
    if mode == MOD_ZOOM:
        # Ctrl stays on the event. The app decides what zooming means and
        # reads the physical Ctrl state to do it, so stripping the flag would
        # turn a zoom back into a scroll.
        gain = settings.mod_gain
        return WheelPlan(
            mode=MOD_ZOOM,
            v_scale=-gain if settings.invert_zoom else gain,
            h_scale=0.0,
        )
    if mode == MOD_FAST:
        # Cmd+wheel is already zoom in Safari, Chrome, Figma and most document
        # apps, so the flag has to come off or fast scroll reads as a zoom.
        return WheelPlan(
            mode=MOD_FAST,
            v_scale=settings.mod_gain,
            h_scale=0.0,
            strip_mods=MOD_META,
        )
    return _NOOP_PLAN


class ScrollAccumulator:
    """Scales wheel deltas and carries the fraction across events.

    At a gain of 0.1 a unit lands every tenth detent rather than on every one:
    that is what the slider says, and forcing a minimum step of 1 would make
    every gain below 1.0 behave identically to 1.0. ``min_step`` exists for a
    caller that genuinely cannot represent "no movement yet".
    """

    __slots__ = ("_residue",)

    def __init__(self):
        self._residue = 0.0

    def feed(self, raw_units, scale, min_step=0):
        try:
            amount = float(raw_units) * float(scale)
        except (TypeError, ValueError):
            return 0
        if not math.isfinite(amount) or amount == 0.0:
            return 0
        self._residue += amount
        whole = math.trunc(self._residue
                           + math.copysign(_UNIT_EPS, self._residue))
        self._residue -= whole
        if whole == 0 and min_step:
            whole = math.copysign(min_step, amount)
            self._residue -= whole
        return int(whole)

    @property
    def residue(self):
        return self._residue

    def reset(self):
        self._residue = 0.0
