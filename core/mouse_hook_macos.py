"""
macOS mouse hook implementation.
"""

import functools
import queue
import sys
import threading
import time

from core.mouse_hook_base import BaseMouseHook, HidGestureListener
from core.mouse_hook_types import MouseEvent, hscroll_event_type
from core.scroll_engine import AXIS_H, AXIS_V
from core.scroll_modifiers import (
    MOD_ALT,
    MOD_CTRL_BIT,
    MOD_META,
    MOD_SHIFT_BIT,
    ScrollAccumulator,
    modifier_names,
    resolve_wheel_action,
)

try:
    import objc
except ImportError as exc:
    raise ImportError(
        "PyObjC is required on macOS. Run "
        "`python -m pip install -r requirements.txt`."
    ) from exc

try:
    import Quartz

    _QUARTZ_OK = True
except ImportError:
    _QUARTZ_OK = False
    print(
        "[MouseHook] pyobjc-framework-Quartz not installed — "
        "pip install pyobjc-framework-Quartz"
    )


def _autoreleased(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with objc.autorelease_pool():
            return fn(*args, **kwargs)
    return wrapper


_BTN_MIDDLE = 2
_BTN_BACK = 3
_BTN_FORWARD = 4
# Quartz other-button number -> per-button slide-gesture owner name (the config
# button keys back/forward/middle map to).
_BTN_TO_GESTURE_OWNER = {
    _BTN_MIDDLE: "middle",
    _BTN_BACK: "xbutton1",
    _BTN_FORWARD: "xbutton2",
}
_SCROLL_INVERT_MARKER = 0x4D4F5553
_INJECTED_EVENT_MARKER = 0x4D4F5554
_SHIFT_WHEEL_HSCROLL_MARKER = 0x4D4F5556
# 0x4D4F5557 is claimed by the pan feature on an open branch; taking it here
# would make each feature swallow the other's injected events.
_SMOOTH_SCROLL_MARKER = 0x4D4F5558

# Quartz flag names rather than values: the constants only exist once
# PyObjC has imported, and this module is imported on every platform.
_CG_FLAG_BITS = (
    ("kCGEventFlagMaskShift", MOD_SHIFT_BIT),
    ("kCGEventFlagMaskControl", MOD_CTRL_BIT),
    ("kCGEventFlagMaskAlternate", MOD_ALT),
    ("kCGEventFlagMaskCommand", MOD_META),
)


def _cg_flag(name):
    """One Quartz flag constant, or 0 when this build does not define it.

    The isinstance check matters: a missing constant on a MagicMock stand-in
    returns a truthy object, and `flags & that` yields another truthy object,
    which would report every modifier as held.
    """
    flag = getattr(Quartz, name, 0)
    return flag if isinstance(flag, int) else 0


def _cg_flags_for(mask):
    """Quartz flag bits for a ``core.scroll_modifiers`` mask."""
    flags = 0
    for name, bit in _CG_FLAG_BITS:
        if mask & bit:
            flags |= _cg_flag(name)
    return flags
_kCGEventTapDisabledByTimeout = 0xFFFFFFFE
_kCGEventTapDisabledByUserInput = 0xFFFFFFFF


class MouseHook(BaseMouseHook):
    """
    Uses CGEventTap on macOS to intercept mouse button presses and scroll
    events. Requires Accessibility permission.
    """

    def __init__(self):
        super().__init__()
        self._running = False
        self._tap = None
        self._tap_source = None
        self.ignore_trackpad = True
        self._wake_observer = None
        self._screens_wake_observer = None
        self._session_resign_observer = None
        self._session_activate_observer = None
        self._last_resume_at = 0.0
        self._init_dispatch_queue(maxsize=512)
        self._dispatch_thread = None
        self._first_event_logged = False

    def _negate_scroll_axis(self, cg_event, axis):
        for field_name in (
            f"kCGScrollWheelEventDeltaAxis{axis}",
            f"kCGScrollWheelEventFixedPtDeltaAxis{axis}",
            f"kCGScrollWheelEventPointDeltaAxis{axis}",
        ):
            field = getattr(Quartz, field_name, None)
            if field is None:
                continue
            value = Quartz.CGEventGetIntegerValueField(cg_event, field)
            if value:
                Quartz.CGEventSetIntegerValueField(cg_event, field, -value)

    def _post_mod_scroll_event(self, cg_event, plan):
        """Re-post a wheel event translated by ``plan``.

        A horizontal plan moves the axis-1 deltas onto axis-2 and zeroes
        axis-1; a vertical plan (fast scroll, zoom) scales axis-1 in place.
        ``plan.strip_mods`` clears the modifiers whose meaning the translation
        has consumed, so an app that also translates Shift+wheel itself does
        not translate it twice.
        """
        v_line = Quartz.CGEventGetIntegerValueField(
            cg_event, Quartz.kCGScrollWheelEventDeltaAxis1
        )
        v_fixed = Quartz.CGEventGetIntegerValueField(
            cg_event, Quartz.kCGScrollWheelEventFixedPtDeltaAxis1
        )
        v_point = Quartz.CGEventGetIntegerValueField(
            cg_event, Quartz.kCGScrollWheelEventPointDeltaAxis1
        )

        horizontal = plan.h_scale != 0.0
        scale = plan.h_scale if horizontal else plan.v_scale
        # Line counts are whole; rounding each independently would let the
        # fixed-point and line views of the same motion disagree in sign.
        v_line = int(round(v_line * scale))
        v_fixed = int(round(v_fixed * scale))
        v_point = int(round(v_point * scale))

        is_continuous = Quartz.CGEventGetIntegerValueField(cg_event, 88)
        if is_continuous:
            unit = Quartz.kCGScrollEventUnitPixel
            primary_delta = v_point
        else:
            unit = Quartz.kCGScrollEventUnitLine
            primary_delta = v_line

        new_event = Quartz.CGEventCreateScrollWheelEvent(
            None, unit, 2,
            0 if horizontal else primary_delta,
            primary_delta if horizontal else 0,
        )
        if not new_event:
            return False

        flags = Quartz.CGEventGetFlags(cg_event)
        Quartz.CGEventSetFlags(new_event, flags & ~_cg_flags_for(plan.strip_mods))
        Quartz.CGEventSetIntegerValueField(
            new_event,
            Quartz.kCGEventSourceUserData,
            _SHIFT_WHEEL_HSCROLL_MARKER,
        )

        axis_fields = (
            ("kCGScrollWheelEventDeltaAxis2", v_line),
            ("kCGScrollWheelEventFixedPtDeltaAxis2", v_fixed),
            ("kCGScrollWheelEventPointDeltaAxis2", v_point),
            ("kCGScrollWheelEventDeltaAxis1", 0),
            ("kCGScrollWheelEventFixedPtDeltaAxis1", 0),
            ("kCGScrollWheelEventPointDeltaAxis1", 0),
        ) if horizontal else (
            ("kCGScrollWheelEventDeltaAxis1", v_line),
            ("kCGScrollWheelEventFixedPtDeltaAxis1", v_fixed),
            ("kCGScrollWheelEventPointDeltaAxis1", v_point),
            ("kCGScrollWheelEventDeltaAxis2", 0),
            ("kCGScrollWheelEventFixedPtDeltaAxis2", 0),
            ("kCGScrollWheelEventPointDeltaAxis2", 0),
        )

        for field_name, value in axis_fields:
            field = getattr(Quartz, field_name, None)
            if field is None:
                continue
            Quartz.CGEventSetIntegerValueField(new_event, field, value)

        for field_name in (
            "kCGScrollWheelEventScrollPhase",
            "kCGScrollWheelEventMomentumPhase",
        ):
            field = getattr(Quartz, field_name, None)
            if field is None:
                continue
            value = Quartz.CGEventGetIntegerValueField(cg_event, field)
            Quartz.CGEventSetIntegerValueField(new_event, field, value)

        Quartz.CGEventPost(Quartz.kCGHIDEventTap, new_event)
        return True

    def _post_inverted_scroll_event(self, cg_event):
        v_point = Quartz.CGEventGetIntegerValueField(
            cg_event, Quartz.kCGScrollWheelEventPointDeltaAxis1
        )
        h_point = Quartz.CGEventGetIntegerValueField(
            cg_event, Quartz.kCGScrollWheelEventPointDeltaAxis2
        )
        if self.invert_vscroll:
            v_point = -v_point
        if self.invert_hscroll:
            h_point = -h_point

        inverted = Quartz.CGEventCreateScrollWheelEvent(
            None,
            Quartz.kCGScrollEventUnitPixel,
            2,
            v_point,
            h_point,
        )
        if not inverted:
            return False
        Quartz.CGEventSetFlags(inverted, Quartz.CGEventGetFlags(cg_event))
        Quartz.CGEventSetIntegerValueField(
            inverted, Quartz.kCGEventSourceUserData, _SCROLL_INVERT_MARKER
        )
        for axis in (1, 2):
            sign = -1 if (
                (axis == 1 and self.invert_vscroll)
                or (axis == 2 and self.invert_hscroll)
            ) else 1
            for field_name in (
                f"kCGScrollWheelEventDeltaAxis{axis}",
                f"kCGScrollWheelEventFixedPtDeltaAxis{axis}",
                f"kCGScrollWheelEventPointDeltaAxis{axis}",
            ):
                field = getattr(Quartz, field_name, None)
                if field is None:
                    continue
                value = Quartz.CGEventGetIntegerValueField(cg_event, field)
                Quartz.CGEventSetIntegerValueField(inverted, field, sign * value)
        for field_name in (
            "kCGScrollWheelEventScrollPhase",
            "kCGScrollWheelEventMomentumPhase",
        ):
            field = getattr(Quartz, field_name, None)
            if field is None:
                continue
            value = Quartz.CGEventGetIntegerValueField(cg_event, field)
            Quartz.CGEventSetIntegerValueField(inverted, field, value)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, inverted)
        return True

    # ── Software scroll engine ────────────────────────────────────────────

    def modifier_state(self, native_event=None):
        """Modifiers from the flags the scroll event already carries.

        No kCGEventFlagsChanged tap: watching every keystroke to learn what is
        held would make Mouser a keylogger as far as the OS is concerned, and
        the scroll event answers the question by itself.
        """
        if not _QUARTZ_OK or native_event is None:
            return 0
        flags = Quartz.CGEventGetFlags(native_event)
        mask = 0
        for name, bit in _CG_FLAG_BITS:
            flag = _cg_flag(name)
            if flag and (flags & flag):
                mask |= bit
        return mask

    def _make_scroll_emitter(self):
        if not _QUARTZ_OK:
            return None
        return self._emit_smooth_scroll

    def _scroll_frame_wrapper(self):
        # Per frame, not per loop: a pool held open across the loop never
        # drains, so every autoreleased object from every frame of a glide
        # piles up until the loop exits.
        return objc.autorelease_pool if objc is not None else None

    def _emit_smooth_scroll(self, dy, dx):
        """Inject one frame of the glide as a pixel-unit scroll event."""
        if not _QUARTZ_OK:
            return
        event = Quartz.CGEventCreateScrollWheelEvent(
            None, Quartz.kCGScrollEventUnitPixel, 2, int(dy), int(dx)
        )
        if not event:
            return
        Quartz.CGEventSetIntegerValueField(
            event, Quartz.kCGEventSourceUserData, _SMOOTH_SCROLL_MARKER
        )
        # ScrollPhase and MomentumPhase stay at 0 deliberately. Setting them
        # makes applications treat the stream as a trackpad gesture, which
        # brings rubber-band overscroll and, in some apps, deltas ignored
        # outright.
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def _post_zoom_events(self, cg_event, outcome):
        """Re-post a Ctrl+wheel tick as ``outcome.passthrough_repeats`` steps.

        The Control flag is copied through untouched: the application reads it
        to decide this is a zoom at all.
        """
        if not _QUARTZ_OK:
            return False
        line = Quartz.CGEventGetIntegerValueField(
            cg_event, Quartz.kCGScrollWheelEventDeltaAxis1
        )
        step = outcome.passthrough_direction * max(1, abs(int(line)) or 1)
        flags = Quartz.CGEventGetFlags(cg_event)
        posted = False
        for _ in range(outcome.passthrough_repeats):
            event = Quartz.CGEventCreateScrollWheelEvent(
                None, Quartz.kCGScrollEventUnitLine, 2, step, 0
            )
            if not event:
                break
            Quartz.CGEventSetFlags(event, flags)
            Quartz.CGEventSetIntegerValueField(
                event, Quartz.kCGEventSourceUserData,
                _SHIFT_WHEEL_HSCROLL_MARKER,
            )
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            posted = True
        return posted

    def _handle_wheel_translation(self, cg_event, v_fixed, h_delta, mask,
                                  from_trackpad):
        """Modifier translation and smooth injection. True means swallow."""
        engine = self._scroll_engine
        # A trackpad stream is already continuous and already animated by the
        # OS. Smoothing it again is catastrophic, and this gate is independent
        # of ignore_trackpad, which only governs mapped-action dispatch.
        if engine is not None and engine.config.enabled and not from_trackpad:
            return self._push_smooth_scroll(cg_event, v_fixed, h_delta, mask)
        if self._mod_scroll is None or h_delta != 0 or v_fixed == 0:
            return False
        plan = resolve_wheel_action(mask, self._mod_scroll)
        if plan.is_noop:
            return False
        return self._post_mod_scroll_event(cg_event, plan)

    def _push_smooth_scroll(self, cg_event, v_fixed, h_delta, mask):
        engine = self._scroll_engine
        names = modifier_names(mask)
        swallow = False
        if v_fixed:
            v = v_fixed / 65536.0
            outcome = engine.push_tick(
                AXIS_V, 1 if v > 0 else -1, abs(v), modifiers=names
            )
            if outcome.passthrough_repeats:
                if self._post_zoom_events(cg_event, outcome):
                    return True
            swallow = swallow or outcome.swallow
        if h_delta:
            outcome = engine.push_tick(
                AXIS_H, 1 if h_delta > 0 else -1, abs(h_delta), modifiers=names
            )
            swallow = swallow or outcome.swallow
        if swallow and self._scroll_driver is not None:
            self._scroll_driver.wake()
        return swallow

    def _emit_gesture_swipe(self, mouse_event):
        self._enqueue_dispatch_event(mouse_event)

    def _dispatch_worker(self):
        while self._running:
            try:
                event = self._dispatch_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            # Action execution downstream of _dispatch creates Quartz
            # CGEvent / NSEvent objects (key_simulator). This worker runs on
            # its own thread, which has no NSAutoreleasePool, so without an
            # explicit pool every autoreleased Foundation temporary produced
            # while injecting a keystroke or mouse click leaks for the process
            # lifetime -- the memory-growth-per-click reported in #233. The
            # CGEventTap callback is already wrapped (@_autoreleased); this
            # covers the second thread that touches Foundation objects.
            with objc.autorelease_pool():
                self._dispatch(event)

    @_autoreleased
    def _event_tap_callback(self, proxy, event_type, cg_event, refcon):
        try:
            if event_type in (
                _kCGEventTapDisabledByTimeout,
                _kCGEventTapDisabledByUserInput,
            ):
                print(
                    f"[MouseHook] CGEventTap disabled by system "
                    f"(type=0x{event_type:X}), re-enabling",
                    flush=True,
                )
                # A pending owner-gesture release may have been dropped while
                # the tap was disabled -- abort it so the cursor can't freeze.
                self.abort_button_gesture("tap_disabled")
                Quartz.CGEventTapEnable(self._tap, True)
                return cg_event

            if not self._first_event_logged:
                self._first_event_logged = True
                print("[MouseHook] CGEventTap: first event received", flush=True)

            try:
                if (
                    Quartz.CGEventGetIntegerValueField(
                        cg_event, Quartz.kCGEventSourceUserData
                    )
                    == _INJECTED_EVENT_MARKER
                ):
                    return cg_event
            except Exception:
                pass

            # KVM / cold-start guard: when no Logitech is currently bound to
            # this host, the CGEventTap must be a complete pass-through. The
            # tap sees events from every mouse the OS knows about, so without
            # this guard a trackpad swipe or a generic USB mouse's xbutton
            # click would get routed through Mouser's remap pipeline -- the
            # exact failure mode users hit when their KVM switches the
            # Logitech to another machine while Mouser keeps running on
            # this one.
            if not self._should_intercept_events():
                return cg_event

            mouse_event = None
            should_block = False

            # ── Per-button slide gestures (back/forward/middle) ──────────
            # Motion while an owner button is held feeds the shared recognizer
            # and is swallowed (return None) so the cursor freezes during the
            # gesture. Fast None-check when no owner is armed.
            if (
                self._button_gesture_active_owner is not None
                and event_type in (
                    Quartz.kCGEventMouseMoved,
                    Quartz.kCGEventOtherMouseDragged,
                )
            ):
                dx = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGMouseEventDeltaX
                )
                dy = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGMouseEventDeltaY
                )
                self.sample_button_gesture(dx, dy, "os_motion")
                return None

            if (
                event_type
                in (
                    Quartz.kCGEventMouseMoved,
                    Quartz.kCGEventOtherMouseDragged,
                )
                and self._gesture_active
            ):
                if not self._gesture_direction_enabled:
                    return cg_event
                dx = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGMouseEventDeltaX
                )
                dy = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGMouseEventDeltaY
                )
                self._emit_debug(
                    f"Gesture move event type={int(event_type)} dx={dx} dy={dy}"
                )
                self._gesture_recognizer.sample(dx, dy, "event_tap")
                return None

            if event_type == Quartz.kCGEventOtherMouseDown:
                btn = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGMouseEventButtonNumber
                )
                if self.debug_mode and self._debug_callback:
                    try:
                        self._debug_callback(f"OtherMouseDown btn={btn}")
                    except Exception:
                        pass
                owner = _BTN_TO_GESTURE_OWNER.get(btn)
                if (owner is not None and self.is_button_gesture_owner(owner)
                        and self.arm_button_gesture(owner)):
                    # Armed as a gesture pad -- swallow the press; motion feeds
                    # the recognizer and the release resolves it.
                    return None
                if btn == _BTN_MIDDLE:
                    mouse_event = MouseEvent(MouseEvent.MIDDLE_DOWN)
                    should_block = MouseEvent.MIDDLE_DOWN in self._blocked_events
                elif btn == _BTN_BACK:
                    mouse_event = MouseEvent(MouseEvent.XBUTTON1_DOWN)
                    should_block = MouseEvent.XBUTTON1_DOWN in self._blocked_events
                elif btn == _BTN_FORWARD:
                    mouse_event = MouseEvent(MouseEvent.XBUTTON2_DOWN)
                    should_block = MouseEvent.XBUTTON2_DOWN in self._blocked_events

            elif event_type == Quartz.kCGEventOtherMouseUp:
                btn = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGMouseEventButtonNumber
                )
                if self.debug_mode and self._debug_callback:
                    try:
                        self._debug_callback(f"OtherMouseUp btn={btn}")
                    except Exception:
                        pass
                owner = _BTN_TO_GESTURE_OWNER.get(btn)
                if (owner is not None
                        and self._button_gesture_active_owner == owner):
                    # owner-button up while armed -> resolve and swallow.
                    self.release_button_gesture(owner)
                    return None
                if btn == _BTN_MIDDLE:
                    mouse_event = MouseEvent(MouseEvent.MIDDLE_UP)
                    should_block = MouseEvent.MIDDLE_UP in self._blocked_events
                elif btn == _BTN_BACK:
                    mouse_event = MouseEvent(MouseEvent.XBUTTON1_UP)
                    should_block = MouseEvent.XBUTTON1_UP in self._blocked_events
                elif btn == _BTN_FORWARD:
                    mouse_event = MouseEvent(MouseEvent.XBUTTON2_UP)
                    should_block = MouseEvent.XBUTTON2_UP in self._blocked_events

            elif event_type == Quartz.kCGEventScrollWheel:
                source_marker = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGEventSourceUserData
                )
                if source_marker in (
                    _SCROLL_INVERT_MARKER,
                    _SHIFT_WHEEL_HSCROLL_MARKER,
                    _SMOOTH_SCROLL_MARKER,
                ):
                    return cg_event
                # Both phases are read whatever ignore_trackpad says. That
                # setting governs mapped-action dispatch; the smooth engine
                # needs to know a trackpad produced this event regardless,
                # because that stream is already continuous.
                scroll_phase = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGScrollWheelEventScrollPhase
                )
                momentum_phase = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGScrollWheelEventMomentumPhase
                )
                from_trackpad = scroll_phase != 0 or momentum_phase != 0
                if self.ignore_trackpad and from_trackpad:
                    return cg_event
                h_delta = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGScrollWheelEventFixedPtDeltaAxis2
                )
                h_delta = h_delta / 65536.0
                if self.debug_mode and self._debug_callback:
                    try:
                        v_delta = (
                            Quartz.CGEventGetIntegerValueField(
                                cg_event,
                                Quartz.kCGScrollWheelEventFixedPtDeltaAxis1,
                            )
                            / 65536.0
                        )
                        self._debug_callback(f"ScrollWheel v={v_delta} h={h_delta}")
                    except Exception:
                        pass
                v_fixed = Quartz.CGEventGetIntegerValueField(
                    cg_event, Quartz.kCGScrollWheelEventFixedPtDeltaAxis1
                )
                # Mapped horizontal actions are resolved first and win: a wheel
                # tilt bound to "volume up" must fire that action and nothing
                # else, not also pan whatever is under the pointer.
                event_type = hscroll_event_type(h_delta)
                if event_type:
                    mouse_event = MouseEvent(event_type, abs(h_delta))
                    should_block = event_type in self._blocked_events
                if mouse_event:
                    self._enqueue_dispatch_event(mouse_event)
                    mouse_event = None
                if should_block:
                    return None
                mask = self.modifier_state(cg_event)
                if self._handle_wheel_translation(
                    cg_event, v_fixed, h_delta, mask, from_trackpad
                ):
                    return None
                if (self.invert_vscroll or self.invert_hscroll) and not self.wheel_native_invert_active:
                    if self._post_inverted_scroll_event(cg_event):
                        return None

            if mouse_event:
                self._enqueue_dispatch_event(mouse_event)

            if should_block:
                return None
            return cg_event

        except Exception as exc:
            print(f"[MouseHook] event tap callback error: {exc}")
            return cg_event

    def _on_hid_mode_shift_down(self):
        self._emit_debug("HID mode shift button down")
        self._dispatch(MouseEvent(MouseEvent.MODE_SHIFT_DOWN))

    def _on_hid_mode_shift_up(self):
        self._emit_debug("HID mode shift button up")
        self._dispatch(MouseEvent(MouseEvent.MODE_SHIFT_UP))

    def _on_hid_dpi_switch_down(self):
        self._emit_debug("HID DPI switch button down")
        self._dispatch(MouseEvent(MouseEvent.DPI_SWITCH_DOWN))

    def _on_hid_dpi_switch_up(self):
        self._emit_debug("HID DPI switch button up")
        self._dispatch(MouseEvent(MouseEvent.DPI_SWITCH_UP))

    # Give the macOS HID stack a moment to return, then replace the stale
    # pre-sleep handle once. HidGestureListener owns all subsequent retries;
    # queueing more force requests while it reconnects would tear down each
    # fresh connection as soon as it opens.
    _RESUME_RECONNECT_DELAY_S = 0.5
    _RESUME_DEDUPE_S = 5.0

    def _start_resume_recovery(self, reason):
        # A full wake commonly raises both system-wake and screens-wake.
        # Collapse that burst into one recovery pass.
        now = time.monotonic()
        if now - self._last_resume_at < self._RESUME_DEDUPE_S:
            return False
        self._last_resume_at = now
        print(f"[MouseHook] Resume detected ({reason}) — recovering")
        threading.Thread(
            target=self._resume_recovery_worker,
            daemon=True,
            name="MouseHook-resume",
        ).start()
        return True

    def _resume_recovery_worker(self):
        time.sleep(self._RESUME_RECONNECT_DELAY_S)
        if not self._running or not self._device_connected:
            return
        hg = self._hid_gesture
        if hg is None:
            return
        try:
            hg.force_reconnect()
        except Exception as exc:
            print(f"[MouseHook] resume reconnect request failed: {exc}")

    def _register_wake_observer(self):
        try:
            from AppKit import NSWorkspace
        except ImportError:
            return
        notification_center = NSWorkspace.sharedWorkspace().notificationCenter()
        hg = self._hid_gesture

        def _re_enable_tap_and_reconnect(reason, reconnect=True):
            if self._tap and self._running:
                Quartz.CGEventTapEnable(self._tap, True)
                ok = Quartz.CGEventTapIsEnabled(self._tap)
                print(
                    f"[MouseHook] Event tap re-enabled ({reason}): "
                    f"{'OK' if ok else 'FAILED — may need restart'}",
                    flush=True,
                )
            if hg and reconnect:
                hg.force_reconnect()

        def _on_wake(notification):
            _re_enable_tap_and_reconnect("wake", reconnect=False)
            self._start_resume_recovery("system wake")

        def _on_screens_wake(notification):
            _re_enable_tap_and_reconnect("screens wake", reconnect=False)
            self._start_resume_recovery("screens wake")

        def _on_session_resign(notification):
            print("[MouseHook] Session deactivated", flush=True)

        def _on_session_activate(notification):
            _re_enable_tap_and_reconnect("user-switch")

        self._wake_observer = notification_center.addObserverForName_object_queue_usingBlock_(
            "NSWorkspaceDidWakeNotification",
            None,
            None,
            _on_wake,
        )
        self._screens_wake_observer = notification_center.addObserverForName_object_queue_usingBlock_(
            "NSWorkspaceScreensDidWakeNotification",
            None,
            None,
            _on_screens_wake,
        )
        self._session_resign_observer = (
            notification_center.addObserverForName_object_queue_usingBlock_(
                "NSWorkspaceSessionDidResignActiveNotification",
                None,
                None,
                _on_session_resign,
            )
        )
        self._session_activate_observer = (
            notification_center.addObserverForName_object_queue_usingBlock_(
                "NSWorkspaceSessionDidBecomeActiveNotification",
                None,
                None,
                _on_session_activate,
            )
        )

    def _unregister_wake_observer(self):
        try:
            from AppKit import NSWorkspace

            notification_center = NSWorkspace.sharedWorkspace().notificationCenter()
            for attr in (
                "_wake_observer",
                "_screens_wake_observer",
                "_session_resign_observer",
                "_session_activate_observer",
            ):
                observer = getattr(self, attr, None)
                if observer is not None:
                    notification_center.removeObserver_(observer)
                    setattr(self, attr, None)
        except Exception:
            pass

    def start(self):
        if not _QUARTZ_OK:
            print("[MouseHook] Quartz not available — hook not installed")
            return False
        if self._running:
            return True

        event_mask = (
            Quartz.CGEventMaskBit(Quartz.kCGEventMouseMoved)
            | Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseUp)
            | Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseDragged)
            | Quartz.CGEventMaskBit(Quartz.kCGEventScrollWheel)
        )

        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            event_mask,
            self._event_tap_callback,
            None,
        )

        if self._tap is None:
            print("[MouseHook] ERROR: Failed to create CGEventTap!")
            print("[MouseHook] Grant Accessibility permission in:")
            print(
                "[MouseHook]   System Settings -> Privacy & Security -> Accessibility"
            )
            return False

        print("[MouseHook] CGEventTap created successfully", flush=True)

        self._tap_source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            self._tap_source,
            Quartz.kCFRunLoopCommonModes,
        )
        Quartz.CGEventTapEnable(self._tap, True)
        print("[MouseHook] CGEventTap enabled and integrated with run loop", flush=True)
        self._running = True

        self._dispatch_thread = threading.Thread(
            target=self._dispatch_worker,
            daemon=True,
            name="MouseHook-dispatch",
        )
        self._dispatch_thread.start()

        self._start_hid_listener()
        self._register_wake_observer()
        return True

    def stop(self):
        self._unregister_wake_observer()
        self._running = False
        self.abort_button_gesture("stop")
        self._stop_hid_listener()
        self._connected_device = None

        if self._tap:
            Quartz.CGEventTapEnable(self._tap, False)
            if self._tap_source:
                Quartz.CFRunLoopRemoveSource(
                    Quartz.CFRunLoopGetCurrent(),
                    self._tap_source,
                    Quartz.kCFRunLoopCommonModes,
                )
                self._tap_source = None
            self._tap = None
            print("[MouseHook] CGEventTap disabled and removed", flush=True)

        if self._dispatch_thread:
            self._dispatch_thread.join(timeout=1)
            self._dispatch_thread = None


MouseHook._platform_module = sys.modules[__name__]


__all__ = [
    "MouseHook",
    "HidGestureListener",
    "Quartz",
    "_QUARTZ_OK",
    "_BTN_MIDDLE",
    "_BTN_BACK",
    "_BTN_FORWARD",
    "_SCROLL_INVERT_MARKER",
    "_INJECTED_EVENT_MARKER",
    "_SHIFT_WHEEL_HSCROLL_MARKER",
    "_kCGEventTapDisabledByTimeout",
    "_kCGEventTapDisabledByUserInput",
]
