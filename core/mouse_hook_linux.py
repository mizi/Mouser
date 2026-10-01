"""
Linux mouse hook implementation.
"""

import glob
import os
import stat
import sys
import threading
import time

try:
    import select as _select_mod
    import evdev as _evdev_mod
    from evdev import InputDevice as _InputDevice
    from evdev import UInput as _UInput
    from evdev import ecodes as _ecodes

    _EVDEV_OK = True
except ImportError:
    _EVDEV_OK = False
    print("[MouseHook] python-evdev not installed — pip install evdev")

from core.logi_devices import (
    build_evdev_connected_device_info,
    resolve_device as _resolve_logi_device,
)
from core.mouse_hook_base import BaseMouseHook, HidGestureListener
from core.mouse_hook_types import HidRuntimeState, MouseEvent, hscroll_event_type
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

_LOGI_VENDOR = 0x046D
_LOG_ONCE_KEYS = set()
_REMAP_REASON_UINPUT_FAILED = "uinput_failed"
_REMAP_REASON_GRAB_FAILED = "grab_failed"
_REMAP_STATUS_MESSAGES = {
    _REMAP_REASON_UINPUT_FAILED: (
        "Linux evdev remapping is degraded: the virtual input device could not "
        "be created. Physical button/wheel interception is unavailable, but "
        "HID++ controls may still work."
    ),
    _REMAP_REASON_GRAB_FAILED: (
        "Linux evdev remapping is degraded: the mouse could not be grabbed. "
        "Physical button/wheel interception is unavailable, but HID++ controls "
        "may still work."
    ),
}
_REMAP_RECOVERY_STATUS = "Linux evdev remapping restored."


# evdev key code -> core.scroll_modifiers bit. Built lazily against _ecodes so
# the module still imports where python-evdev is absent.
def _build_modifier_key_bits():
    if not _EVDEV_OK:
        return {}
    pairs = (
        ("KEY_LEFTSHIFT", MOD_SHIFT_BIT),
        ("KEY_RIGHTSHIFT", MOD_SHIFT_BIT),
        ("KEY_LEFTCTRL", MOD_CTRL_BIT),
        ("KEY_RIGHTCTRL", MOD_CTRL_BIT),
        ("KEY_LEFTALT", MOD_ALT),
        ("KEY_RIGHTALT", MOD_ALT),
        ("KEY_LEFTMETA", MOD_META),
        ("KEY_RIGHTMETA", MOD_META),
    )
    table = {}
    for name, bit in pairs:
        code = getattr(_ecodes, name, None)
        if code is not None:
            table[code] = bit
    return table


_MODIFIER_KEY_BITS = _build_modifier_key_bits()

# One EVIOCGKEY ioctl per keyboard per read, so a hi-res burst of ~15 events
# would otherwise cost 15 ioctls per device for an answer that cannot have
# changed.
_MOD_CACHE_TTL_S = 0.012

# A scroll frame is in pixels; libinput's notional detent is 120 hi-res units,
# and 40 px per detent matches the usual three-lines default.
HI_RES_UNITS_PER_PX = 120.0 / 40.0



def _log_once(key, message):
    if key in _LOG_ONCE_KEYS:
        return
    _LOG_ONCE_KEYS.add(key)
    print(message)


def _owner_name(uid):
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except Exception:
        return str(uid)


def _group_name(gid):
    try:
        import grp
        return grp.getgrgid(gid).gr_name
    except Exception:
        return str(gid)


def _format_linux_device_access(path):
    if not path:
        return "path=-"
    try:
        st = os.stat(path)
    except OSError as exc:
        return f"path={path} stat_error={exc}"

    mode = stat.S_IMODE(st.st_mode)
    can_read = os.access(path, os.R_OK)
    can_write = os.access(path, os.W_OK)
    can_rw = os.access(path, os.R_OK | os.W_OK)
    return (
        f"path={path} mode={mode:04o} "
        f"owner={_owner_name(st.st_uid)}({st.st_uid}) "
        f"group={_group_name(st.st_gid)}({st.st_gid}) "
        f"access=read:{can_read} write:{can_write} read_write:{can_rw}"
    )


def _format_linux_device_access_list(paths, limit=8):
    details = [_format_linux_device_access(path) for path in list(paths)[:limit]]
    remaining = max(0, len(paths) - limit)
    if remaining:
        details.append(f"... {remaining} more")
    return "; ".join(details) if details else "-"


class MouseHook(BaseMouseHook):
    """
    Uses evdev on Linux to intercept mouse button presses and scroll events.
    Grabs the mouse device for exclusive access and forwards non-blocked events
    via a uinput virtual mouse.
    """

    def __init__(self):
        super().__init__()
        self._running = False
        self._evdev_ready = False
        self._hid_ready = False
        self._evdev_connected_device = None
        self._evdev_device = None
        self._uinput = None
        # Every uinput write goes through this. Two threads write now --
        # the evdev reader and the scroll tick thread -- and without it a
        # frame can land between a REL_X and its SYN_REPORT, or a write can
        # race _close_uinput and hit a closed (or recycled) descriptor.
        self._uinput_lock = threading.Lock()
        self._uinput_hi_res = False
        self._mod_v_accum = ScrollAccumulator()
        self._mod_h_accum = ScrollAccumulator()
        self._mod_cache = (0.0, 0)
        self._evdev_thread = None
        self._rescan_requested = threading.Event()
        self._evdev_wakeup = threading.Event()
        self._ignored_non_logitech = set()
        self._ui_passthrough = False
        self._evdev_grabbed = False
        self._evdev_remap_ready = False
        self._evdev_remap_status_state = (False, None)
        self._keyboard_devices = []
        self._keyboard_devices_initialised = False

    @property
    def evdev_ready(self):
        return self._evdev_ready

    @property
    def hid_ready(self):
        return self._hid_ready

    @property
    def evdev_remap_ready(self):
        return self._evdev_remap_ready

    @property
    def hid_runtime_state(self):
        hg = getattr(self, "_hid_gesture", None)
        hid_device = getattr(hg, "connected_device", None) if hg else None
        return HidRuntimeState(
            input_ready=bool(self._device_connected),
            hid_ready=bool(self._hid_ready and hid_device is not None),
            connected_device=self._connected_device,
        )

    def set_ui_passthrough(self, enabled):
        enabled = bool(enabled)
        if self._ui_passthrough == enabled:
            return
        self._ui_passthrough = enabled
        if enabled:
            message = "Linux input passthrough enabled; evdev remapping paused"
            self._disable_evdev_remapping()
            self._rescan_requested.set()
            self._evdev_wakeup.set()
            print(f"[MouseHook] {message}")
            self._emit_status(message)
        else:
            message = "Linux input passthrough disabled; evdev remapping restored"
            self._rescan_requested.clear()
            if self._evdev_device is not None:
                self._enable_evdev_remapping()
            self._evdev_wakeup.set()
            print(f"[MouseHook] {message}")
            self._emit_status(message)

    def _acquire_evdev_grab(self):
        dev = self._evdev_device
        if dev is None or self._evdev_grabbed:
            return self._evdev_grabbed
        try:
            dev.grab()
            self._evdev_grabbed = True
            print(f"[MouseHook] Grabbed {dev.name} ({dev.path})")
            return True
        except Exception as exc:
            print(f"[MouseHook] Failed to grab {getattr(dev, 'path', '?')}: {exc}")
            return False

    def _release_evdev_grab(self):
        dev = self._evdev_device
        if dev is None or not self._evdev_grabbed:
            return
        try:
            dev.ungrab()
            self._evdev_grabbed = False
            print(f"[MouseHook] Released grab for {dev.name} ({dev.path})")
        except Exception as exc:
            print(f"[MouseHook] Failed to ungrab {getattr(dev, 'path', '?')}: {exc}")

    def _set_evdev_remap_ready(self, ready, reason=None):
        ready = bool(ready)
        reason = None if ready else reason
        if reason not in (_REMAP_REASON_UINPUT_FAILED, _REMAP_REASON_GRAB_FAILED):
            reason = None
        next_state = (ready, reason)
        if next_state == self._evdev_remap_status_state:
            self._evdev_remap_ready = ready
            return
        previous_state = self._evdev_remap_status_state
        self._evdev_remap_status_state = next_state
        self._evdev_remap_ready = ready
        if ready:
            if previous_state[1] in (
                _REMAP_REASON_UINPUT_FAILED,
                _REMAP_REASON_GRAB_FAILED,
            ):
                self._emit_status(_REMAP_RECOVERY_STATUS)
            return
        message = _REMAP_STATUS_MESSAGES.get(reason)
        if message:
            self._emit_status(message)

    def _close_uinput(self):
        with self._uinput_lock:
            device, self._uinput = self._uinput, None
        if device:
            try:
                device.close()
            except Exception:
                pass

    def _uinput_write(self, *reports):
        """The single uinput write path.

        Each report is ``("event", evdev_event)`` or ``("rel", code, value)``.
        Everything in one call is written under one lock hold, so a report
        the kernel is meant to see as one motion cannot be split by a frame
        from the scroll thread.
        """
        with self._uinput_lock:
            device = self._uinput
            if device is None:
                return False
            try:
                for report in reports:
                    if report[0] == "event":
                        device.write_event(report[1])
                    else:
                        device.write(_ecodes.EV_REL, report[1], report[2])
            except OSError as exc:
                _log_once(
                    ("uinput-write-error", type(exc).__name__),
                    f"[MouseHook] uinput write failed: {exc}",
                )
                return False
        return True

    def _disable_evdev_remapping(self, reason=None):
        self._set_evdev_remap_ready(False, reason)
        self._release_evdev_grab()
        self._close_uinput()

    def _enable_evdev_remapping(self):
        dev = self._evdev_device
        if dev is None or self._ui_passthrough:
            self._disable_evdev_remapping()
            return False
        if self._evdev_remap_ready:
            return True
        if self._uinput is None:
            hi_res = self._smooth_scroll_wanted()
            try:
                self._uinput = _UInput(
                    events=self._filtered_uinput_events(dev, hi_res=hi_res),
                    name="Mouser Virtual Mouse",
                    vendor=getattr(dev.info, "vendor", 1),
                    product=getattr(dev.info, "product", 1),
                    version=getattr(dev.info, "version", 1),
                    bustype=getattr(dev.info, "bustype", 0x03),
                )
                self._uinput_hi_res = hi_res
            except PermissionError:
                print(
                    "[MouseHook] Permission denied — add user to 'input' group "
                    "and ensure /dev/uinput is writable"
                )
                self._set_evdev_remap_ready(False, _REMAP_REASON_UINPUT_FAILED)
                return False
            except Exception as exc:
                print(f"[MouseHook] Failed to setup uinput: {exc}")
                self._set_evdev_remap_ready(False, _REMAP_REASON_UINPUT_FAILED)
                return False
        if not self._acquire_evdev_grab():
            self._disable_evdev_remapping(_REMAP_REASON_GRAB_FAILED)
            return False
        self._set_evdev_remap_ready(True)
        return True

    def _set_evdev_ready(self, ready):
        if ready == self._evdev_ready:
            return
        self._evdev_ready = ready
        self._refresh_device_state(force=True)

    def _set_device_connected(self, connected, force=False):
        changed = connected != self._device_connected
        if not changed and not force:
            return
        self._device_connected = connected
        if changed:
            state = "Connected" if connected else "Disconnected"
            print(f"[MouseHook] Device {state}")
        if self._connection_change_cb:
            try:
                self._connection_change_cb(connected)
            except Exception:
                pass

    def _build_evdev_connected_device(self, dev):
        info = getattr(dev, "info", None)
        return build_evdev_connected_device_info(
            product_id=getattr(info, "product", None) if info else None,
            product_name=getattr(dev, "name", None),
            transport="evdev",
            source="evdev",
        )

    def _refresh_device_state(self, force=False):
        previous = self._connected_device
        next_device = None
        if self._hid_ready and self._hid_gesture:
            next_device = self._hid_gesture.connected_device
        if next_device is None:
            next_device = self._evdev_connected_device
        self._connected_device = next_device

        prev_source = getattr(previous, "source", None) if previous is not None else None
        next_source = getattr(next_device, "source", None) if next_device is not None else None
        if prev_source != next_source:
            if next_source == "evdev":
                print("[MouseHook] Using evdev fallback device info")
            elif prev_source == "evdev" and next_device is not None:
                print("[MouseHook] Device info upgraded from evdev fallback to HID++")

        self._set_device_connected(self._evdev_ready, force=force)

    def _hid_gesture_available(self):
        return self._hid_gesture is not None and self._evdev_ready

    def _on_hid_mode_shift_down(self):
        if self._ui_passthrough:
            return
        self._emit_debug("HID mode shift button down")
        self._dispatch(MouseEvent(MouseEvent.MODE_SHIFT_DOWN))

    def _on_hid_mode_shift_up(self):
        if self._ui_passthrough:
            return
        self._emit_debug("HID mode shift button up")
        self._dispatch(MouseEvent(MouseEvent.MODE_SHIFT_UP))

    def _on_hid_dpi_switch_down(self):
        if self._ui_passthrough:
            return
        self._emit_debug("HID DPI switch button down")
        self._dispatch(MouseEvent(MouseEvent.DPI_SWITCH_DOWN))

    def _on_hid_dpi_switch_up(self):
        if self._ui_passthrough:
            return
        self._emit_debug("HID DPI switch button up")
        self._dispatch(MouseEvent(MouseEvent.DPI_SWITCH_UP))

    def _on_hid_connect(self):
        self._hid_ready = True
        self._refresh_device_state(force=True)
        dev = self._evdev_device
        should_wake_evdev = (
            self._running
            and _EVDEV_OK
            and (
                dev is None
                or not self._evdev_ready
                or dev.info.vendor != _LOGI_VENDOR
            )
        )
        if should_wake_evdev:
            print("[MouseHook] Logitech HID connected; waking evdev scan")
            self._rescan_requested.set()
            self._evdev_wakeup.set()

    def _on_hid_disconnect(self):
        self._hid_ready = False
        if self._gesture_active:
            self._gesture_active = False
            self._gesture_recognizer.end()
        self._refresh_device_state(force=True)

    def _find_mouse_device(self):
        logi_mice = []
        try:
            paths = list(_evdev_mod.list_devices())
        except Exception as exc:
            _log_once(
                ("evdev-list-error", type(exc).__name__, str(exc)),
                f"[MouseHook] Cannot list evdev devices: {exc}",
            )
            return None
        if not paths:
            event_paths = sorted(glob.glob("/dev/input/event*"))
            if event_paths:
                _log_once(
                    "evdev-empty-fallback-event-nodes",
                    "[MouseHook] evdev returned no input devices; falling "
                    "back to visible /dev/input/event* nodes: "
                    f"{_format_linux_device_access_list(event_paths)}",
                )
                paths = event_paths
            else:
                _log_once(
                    "evdev-no-input-devices",
                    "[MouseHook] evdev returned no input devices and no "
                    "/dev/input/event* nodes are visible; remapping needs "
                    f"/dev/input/event* access. "
                    f"{_format_linux_device_access('/dev/input')}",
                )

        for path in paths:
            try:
                dev = _InputDevice(path)
            except PermissionError as exc:
                _log_once(
                    ("evdev-open-permission", path),
                    f"[MouseHook] Permission denied opening {path}: {exc}. "
                    f"{_format_linux_device_access(path)}. "
                    "Add the user to a group with /dev/input/event* access "
                    "or install a udev rule.",
                )
                continue
            except Exception as exc:
                _log_once(
                    ("evdev-open-error", path, type(exc).__name__, str(exc)),
                    f"[MouseHook] Cannot open evdev device {path}: {exc}",
                )
                continue
            try:
                caps = dev.capabilities(absinfo=False)
                if _ecodes.EV_REL not in caps or _ecodes.EV_KEY not in caps:
                    dev.close()
                    continue
                rel_caps = set(caps.get(_ecodes.EV_REL, []))
                key_caps = set(caps.get(_ecodes.EV_KEY, []))
                if _ecodes.REL_X not in rel_caps or _ecodes.REL_Y not in rel_caps:
                    dev.close()
                    continue
                if not key_caps.intersection(
                    {
                        _ecodes.BTN_LEFT,
                        _ecodes.BTN_RIGHT,
                        _ecodes.BTN_MIDDLE,
                    }
                ):
                    dev.close()
                    continue
                has_side = bool(
                    key_caps.intersection(
                        {
                            _ecodes.BTN_SIDE,
                            _ecodes.BTN_EXTRA,
                        }
                    )
                )
            except PermissionError as exc:
                _log_once(
                    ("evdev-capabilities-permission", dev.path),
                    f"[MouseHook] Permission denied reading capabilities for "
                    f"{dev.path}: {exc}",
                )
                dev.close()
                continue
            except Exception as exc:
                _log_once(
                    ("evdev-capabilities-error", dev.path, type(exc).__name__, str(exc)),
                    f"[MouseHook] Cannot inspect evdev device {dev.path}: {exc}",
                )
                dev.close()
                continue
            if dev.info.vendor == _LOGI_VENDOR:
                logi_mice.append((dev, has_side))
            else:
                info = getattr(dev, "info", None)
                dedupe_key = (
                    dev.path,
                    getattr(info, "vendor", 0),
                    getattr(info, "product", 0),
                    dev.name or "",
                )
                if dedupe_key not in self._ignored_non_logitech:
                    self._ignored_non_logitech.add(dedupe_key)
                    print(
                        "[MouseHook] Ignoring non-Logitech evdev candidate: "
                        f"{dev.name} ({dev.path}) "
                        f"vendor=0x{getattr(info, 'vendor', 0):04X} "
                        f"product=0x{getattr(info, 'product', 0):04X}"
                    )
                dev.close()

        def _event_num(dev):
            try:
                return int(str(dev.path).rsplit("event", 1)[1])
            except (IndexError, ValueError):
                return -1

        def _sort_key(item):
            dev, has_side = item
            info = getattr(dev, "info", None)
            spec = _resolve_logi_device(
                product_id=getattr(info, "product", None),
                product_name=getattr(dev, "name", None),
            )
            return (
                int(spec is not None),
                int(has_side),
                _event_num(dev),
            )

        ordered = sorted(logi_mice, key=_sort_key, reverse=True)
        if ordered:
            chosen = ordered[0][0]
            for dev, _ in ordered[1:]:
                dev.close()
            print(
                f"[MouseHook] Found mouse: {chosen.name} ({chosen.path}) "
                f"vendor=0x{chosen.info.vendor:04X}"
            )
            return chosen
        _log_once(
            "evdev-no-logitech-mouse",
            "[MouseHook] No Logitech evdev mouse found; UI connection state "
            "and remapping require a Logitech mouse visible under "
            "/dev/input/event* with vendor 0x046D",
        )
        return None

    def _setup_evdev(self):
        dev = self._find_mouse_device()
        if not dev:
            return False
        try:
            self._evdev_device = dev
            self._evdev_grabbed = False
            self._evdev_connected_device = self._build_evdev_connected_device(dev)
            self._set_evdev_ready(True)
            if self._ui_passthrough:
                self._disable_evdev_remapping()
            else:
                self._enable_evdev_remapping()
            return True
        except Exception as exc:
            print(f"[MouseHook] Failed to setup evdev: {exc}")
            dev.close()
        return False

    def _filtered_uinput_events(self, dev, *, hi_res=False):
        """Capabilities for the virtual mouse.

        Hi-res wheel codes are dropped by default: passing both the hi-res and
        the legacy code through for the same motion makes libinput count it
        twice. The smooth engine needs them, and asks for them explicitly.
        """
        caps = dict(dev.capabilities(absinfo=False))
        for filtered_type in (_ecodes.EV_SYN, getattr(_ecodes, "EV_FF", None)):
            if filtered_type is not None:
                caps.pop(filtered_type, None)
        rel_type = _ecodes.EV_REL
        rel_caps = list(caps.get(rel_type, []))
        hi_res_codes = {
            getattr(_ecodes, "REL_WHEEL_HI_RES", None),
            getattr(_ecodes, "REL_HWHEEL_HI_RES", None),
        }
        hi_res_codes.discard(None)
        if hi_res:
            filtered_rel_caps = list(rel_caps)
            for code in sorted(hi_res_codes):
                if code not in filtered_rel_caps:
                    filtered_rel_caps.append(code)
        else:
            filtered_rel_caps = [code for code in rel_caps
                                 if code not in hi_res_codes]
        # Ensure REL_HWHEEL is available so Shift+wheel translation can emit
        # horizontal scroll even on mice without a tilt wheel.  Only add when
        # the source already exposes REL events (i.e. is a mouse-like device).
        if rel_caps and _ecodes.REL_HWHEEL not in filtered_rel_caps:
            filtered_rel_caps.append(_ecodes.REL_HWHEEL)
        if filtered_rel_caps != rel_caps:
            caps[rel_type] = filtered_rel_caps
            if not hi_res and rel_caps and any(c in hi_res_codes
                                               for c in rel_caps):
                print(
                    "[MouseHook] Filtering REL_WHEEL_HI_RES / "
                    "REL_HWHEEL_HI_RES from Mouser Virtual Mouse"
                )
        return caps

    def _ensure_keyboard_devices(self):
        """Open keyboard evdev devices (read-only) for modifier detection."""
        if self._keyboard_devices_initialised or not _EVDEV_OK:
            return
        self._keyboard_devices_initialised = True
        try:
            paths = list(_evdev_mod.list_devices())
        except Exception as exc:
            _log_once(
                ("evdev-keyboard-list-error", type(exc).__name__, str(exc)),
                f"[MouseHook] Cannot list evdev devices for Shift detection: {exc}",
            )
            return
        # Any modifier qualifies, not only Shift: a device that reports Ctrl
        # but no Shift key -- a split keyboard's half, a macro pad -- is still
        # the only place Ctrl+wheel can be observed from.
        modifier_codes = set(_MODIFIER_KEY_BITS)
        keyboards = []
        for path in paths:
            try:
                dev = _InputDevice(path)
            except PermissionError:
                continue
            except Exception:
                continue
            try:
                caps = dev.capabilities(absinfo=False)
                key_caps = set(caps.get(_ecodes.EV_KEY, []))
                if key_caps & modifier_codes:
                    keyboards.append(dev)
                    continue
            except Exception:
                pass
            try:
                dev.close()
            except Exception:
                pass
        self._keyboard_devices = keyboards
        if keyboards:
            print(
                f"[MouseHook] Tracking {len(keyboards)} keyboard device(s) "
                "for modifier+wheel detection"
            )

    def _close_keyboard_devices(self):
        for dev in self._keyboard_devices:
            try:
                dev.close()
            except Exception:
                pass
        self._keyboard_devices = []
        self._keyboard_devices_initialised = False

    def modifier_state(self, native_event=None):
        """Modifiers held right now, as a ``core.scroll_modifiers`` mask.

        Each call is one EVIOCGKEY ioctl per tracked keyboard, so the result is
        cached: a hi-res wheel emits about fifteen events per detent, and a
        modifier cannot meaningfully change inside one burst.
        """
        now = time.monotonic()
        stamp, cached = self._mod_cache
        if now - stamp < _MOD_CACHE_TTL_S:
            return cached
        mask = self._read_modifier_mask()
        self._mod_cache = (now, mask)
        return mask

    def _read_modifier_mask(self):
        if not self._keyboard_devices_initialised:
            self._ensure_keyboard_devices()
        if not self._keyboard_devices:
            return 0
        mask = 0
        stale = []
        for dev in self._keyboard_devices:
            try:
                active = dev.active_keys()
            except OSError:
                stale.append(dev)
                continue
            except Exception:
                continue
            for code in active:
                mask |= _MODIFIER_KEY_BITS.get(code, 0)
        if stale:
            self._drop_stale_keyboards(stale)
        return mask

    def _drop_stale_keyboards(self, stale):
        for dev in stale:
            try:
                dev.close()
            except Exception:
                pass
            try:
                self._keyboard_devices.remove(dev)
            except ValueError:
                pass

    def _cleanup_evdev(self):
        self._disable_evdev_remapping()
        if self._evdev_device:
            try:
                self._evdev_device.close()
            except Exception:
                pass
            self._evdev_device = None
            self._evdev_grabbed = False
            print("[MouseHook] evdev device released")
        self._evdev_connected_device = None
        self._set_evdev_ready(False)

    def _evdev_loop(self):
        while self._running:
            self._rescan_requested.clear()
            if not self._setup_evdev():
                if self._running:
                    self._wait_for_evdev_wakeup(2)
                continue
            try:
                while self._running:
                    if self._rescan_requested.is_set():
                        break
                    if not self._evdev_remap_ready:
                        self._wait_for_evdev_wakeup(None)
                        if self._rescan_requested.is_set():
                            break
                        if (
                            self._running
                            and not self._ui_passthrough
                            and not self._evdev_remap_ready
                        ):
                            self._enable_evdev_remapping()
                        continue
                    self._listen_loop()
                    break
            except OSError as exc:
                if self._running:
                    print(f"[MouseHook] Device disconnected: {exc}")
            except Exception as exc:
                if self._running:
                    print(f"[MouseHook] evdev error: {exc}")
            finally:
                self._cleanup_evdev()
            if self._running:
                if self._rescan_requested.is_set():
                    continue
                self._wait_for_evdev_wakeup(1)

    def _wait_for_evdev_wakeup(self, timeout=None):
        self._evdev_wakeup.wait(timeout)
        self._evdev_wakeup.clear()

    def _listen_loop(self):
        fd = self._evdev_device.fd
        while self._running:
            if self._rescan_requested.is_set():
                print("[MouseHook] Rescan requested; leaving listen loop")
                return
            if not self._evdev_remap_ready:
                self._wait_for_evdev_wakeup(None)
                continue
            readable, _, _ = _select_mod.select([fd], [], [], 0.5)
            if not readable:
                continue
            for event in self._evdev_device.read():
                if not self._running:
                    return
                if self._ui_passthrough:
                    continue
                if event.type == _ecodes.EV_SYN:
                    self._uinput_write(("event", event))
                elif event.type == _ecodes.EV_KEY:
                    self._handle_button(event)
                elif event.type == _ecodes.EV_REL:
                    self._handle_rel(event)
                else:
                    self._uinput_write(("event", event))

    def _handle_button(self, event):
        if self._ui_passthrough or not self._evdev_remap_ready:
            return

        # ── Per-button slide gestures (back/forward/middle) ──────────────
        # An armed owner button's press starts the shared recognizer and its
        # release resolves it; the physical event is neither dispatched nor
        # forwarded to the virtual mouse (so a tap does nothing and a hold+slide
        # fires the direction action). Motion is captured in _handle_rel.
        gesture_owner = None
        if event.code == _ecodes.BTN_SIDE:
            gesture_owner = "xbutton1"
        elif event.code == _ecodes.BTN_EXTRA:
            gesture_owner = "xbutton2"
        elif event.code == _ecodes.BTN_MIDDLE:
            gesture_owner = "middle"
        if gesture_owner is not None:
            if event.value == 1 and self.is_button_gesture_owner(gesture_owner):
                if self.arm_button_gesture(gesture_owner):
                    return
            elif (event.value == 0
                  and self._button_gesture_active_owner == gesture_owner):
                self.release_button_gesture(gesture_owner)
                return

        mouse_event = None
        should_block = False

        if event.code == _ecodes.BTN_SIDE:
            if event.value == 1:
                mouse_event = MouseEvent(MouseEvent.XBUTTON1_DOWN)
                should_block = MouseEvent.XBUTTON1_DOWN in self._blocked_events
            elif event.value == 0:
                mouse_event = MouseEvent(MouseEvent.XBUTTON1_UP)
                should_block = MouseEvent.XBUTTON1_UP in self._blocked_events

        elif event.code == _ecodes.BTN_EXTRA:
            if event.value == 1:
                mouse_event = MouseEvent(MouseEvent.XBUTTON2_DOWN)
                should_block = MouseEvent.XBUTTON2_DOWN in self._blocked_events
            elif event.value == 0:
                mouse_event = MouseEvent(MouseEvent.XBUTTON2_UP)
                should_block = MouseEvent.XBUTTON2_UP in self._blocked_events

        elif event.code == _ecodes.BTN_MIDDLE:
            if event.value == 1:
                mouse_event = MouseEvent(MouseEvent.MIDDLE_DOWN)
                should_block = MouseEvent.MIDDLE_DOWN in self._blocked_events
            elif event.value == 0:
                mouse_event = MouseEvent(MouseEvent.MIDDLE_UP)
                should_block = MouseEvent.MIDDLE_UP in self._blocked_events

        if mouse_event:
            self._dispatch(mouse_event)

        if not should_block:
            self._uinput_write(("event", event))

    def _handle_rel(self, event):
        if self._ui_passthrough or not self._evdev_remap_ready:
            return
        code = event.code
        value = event.value

        if code == _ecodes.REL_X or code == _ecodes.REL_Y:
            # Per-button slide gesture: feed motion to the shared recognizer and
            # suppress it (cursor freeze) while an owner button is held.
            if self._button_gesture_active_owner is not None:
                if code == _ecodes.REL_X:
                    self.sample_button_gesture(value, 0, "os_motion")
                else:
                    self.sample_button_gesture(0, value, "os_motion")
                return
            if self._gesture_direction_enabled and self._gesture_active:
                if code == _ecodes.REL_X:
                    self._gesture_recognizer.sample(value, 0, "evdev")
                else:
                    self._gesture_recognizer.sample(0, value, "evdev")
                return
            self._uinput_write(("event", event))
            return

        rel_wheel_hi_res = getattr(_ecodes, "REL_WHEEL_HI_RES", 0x0B)
        if code == _ecodes.REL_WHEEL or code == rel_wheel_hi_res:
            if value != 0 and self._handle_wheel_translation(code, value, event):
                return
            if self.invert_vscroll and not self.wheel_native_invert_active:
                self._uinput_write(("rel", code, -value))
            else:
                self._uinput_write(("event", event))
            return

        rel_hwheel_hi_res = getattr(_ecodes, "REL_HWHEEL_HI_RES", 0x0C)
        if code == _ecodes.REL_HWHEEL or code == rel_hwheel_hi_res:
            event_type = hscroll_event_type(value)
            should_block = bool(event_type) and event_type in self._blocked_events

            if code == _ecodes.REL_HWHEEL and event_type:
                self._dispatch(MouseEvent(event_type, abs(value)))

            # A mapped tilt action wins outright: a wheel tilt bound to "volume
            # up" must fire that and nothing else, not also pan the page.
            if should_block:
                return
            if value != 0 and self._smooth_scroll_wanted():
                if self._push_smooth_wheel(code, value, self.modifier_state()):
                    return
            if self.invert_hscroll and not self.wheel_native_invert_active:
                self._uinput_write(("rel", code, -value))
            else:
                self._uinput_write(("event", event))
            return

        self._uinput_write(("event", event))

    # ── Software scroll engine ────────────────────────────────────────────

    def _smooth_scroll_wanted(self):
        engine = self._scroll_engine
        return engine is not None and engine.config.enabled

    def configure_smooth_scroll(self, settings):
        """Rebuild the virtual mouse when the hi-res capability has to change.

        uinput capabilities are fixed at creation, so turning smooth scroll on
        or off means destroying and recreating the device. The virtual mouse
        disappears for that instant, and a button held right then can stick --
        unavoidable, and the reason this only happens on a settings change.
        """
        was_hi_res = self._uinput_hi_res
        super().configure_smooth_scroll(settings)
        if self._uinput is None or self._smooth_scroll_wanted() == was_hi_res:
            return
        self._disable_evdev_remapping()
        self._enable_evdev_remapping()

    def _make_scroll_emitter(self):
        if not _EVDEV_OK:
            return None
        return self._emit_smooth_scroll

    def _emit_smooth_scroll(self, dy, dx):
        """Inject one frame of the glide into the virtual mouse.

        No marker is needed: these writes go to the virtual device, which is
        not the one the grab reads from, so they never re-enter the hook.
        """
        reports = []
        wheel_hi_res = getattr(_ecodes, "REL_WHEEL_HI_RES", None)
        hwheel_hi_res = getattr(_ecodes, "REL_HWHEEL_HI_RES", None)
        if dy and wheel_hi_res is not None:
            # Positive REL_WHEEL is up, and a positive frame delta is downward
            # pixel motion, so the sign flips here.
            reports.append(("rel", wheel_hi_res,
                            -int(round(dy * HI_RES_UNITS_PER_PX))))
        if dx and hwheel_hi_res is not None:
            reports.append(("rel", hwheel_hi_res,
                            int(round(dx * HI_RES_UNITS_PER_PX))))
        if reports:
            self._uinput_write(*reports)

    def _handle_wheel_translation(self, code, value, event):
        """Modifier translation or smooth injection. True means consumed."""
        mask = self.modifier_state()
        if self._smooth_scroll_wanted():
            return self._push_smooth_wheel(code, value, mask)
        if self._mod_scroll is None:
            return False
        plan = resolve_wheel_action(mask, self._mod_scroll)
        if plan.is_noop:
            return False
        if code != _ecodes.REL_WHEEL:
            # A hi-res fragment of a burst whose legacy event is translated
            # separately; swallow it so the motion is not counted twice.
            return True
        v_delta = self._mod_v_accum.feed(value, plan.v_scale)
        h_delta = self._mod_h_accum.feed(value, plan.h_scale)
        reports = []
        if h_delta:
            reports.append(("rel", _ecodes.REL_HWHEEL, h_delta))
        if v_delta:
            reports.append(("rel", _ecodes.REL_WHEEL, v_delta))
        if reports:
            self._uinput_write(*reports)
        return True

    def _push_smooth_wheel(self, code, value, mask):
        wheel_hi_res = getattr(_ecodes, "REL_WHEEL_HI_RES", None)
        hwheel_hi_res = getattr(_ecodes, "REL_HWHEEL_HI_RES", None)
        # The kernel sends both the hi-res and the legacy code for the same
        # motion. Taking the hi-res one and ignoring its legacy twin is what
        # keeps one detent from counting as two.
        if code == _ecodes.REL_WHEEL and self._device_has_hi_res_wheel():
            return True
        if code == _ecodes.REL_HWHEEL and self._device_has_hi_res_wheel():
            return True
        if code in (wheel_hi_res, _ecodes.REL_WHEEL):
            axis = AXIS_V
            magnitude = abs(value) / (120.0 if code == wheel_hi_res else 1.0)
            # REL_WHEEL positive is up; the engine's positive is downward.
            direction = -1 if value > 0 else 1
        else:
            axis = AXIS_H
            magnitude = abs(value) / (120.0 if code == hwheel_hi_res else 1.0)
            direction = 1 if value > 0 else -1
        outcome = self._scroll_engine.push_tick(
            axis, direction, magnitude, modifiers=modifier_names(mask)
        )
        if outcome.passthrough_repeats:
            step = -outcome.passthrough_direction
            reports = [("rel", _ecodes.REL_WHEEL, step)
                       for _ in range(outcome.passthrough_repeats)]
            self._uinput_write(*reports)
            return True
        if not outcome.swallow:
            return False
        if self._scroll_driver is not None:
            self._scroll_driver.wake()
        return True

    def _device_has_hi_res_wheel(self):
        if self._evdev_device is None:
            return False
        wheel_hi_res = getattr(_ecodes, "REL_WHEEL_HI_RES", None)
        if wheel_hi_res is None:
            return False
        try:
            caps = self._evdev_device.capabilities(absinfo=False)
        except Exception:
            return False
        return wheel_hi_res in set(caps.get(_ecodes.EV_REL, []))

    def _install_crash_guard(self):
        import atexit
        import signal

        atexit.register(self._cleanup_evdev)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            prev = signal.getsignal(sig)

            def _handler(signum, frame, _prev=prev):
                self._cleanup_evdev()
                if callable(_prev) and _prev not in (signal.SIG_DFL, signal.SIG_IGN):
                    _prev(signum, frame)
                else:
                    raise SystemExit(128 + signum)

            signal.signal(sig, _handler)

    def start(self):
        self._running = True

        self._start_hid_listener()

        if _EVDEV_OK:
            self._install_crash_guard()
            self._evdev_thread = threading.Thread(
                target=self._evdev_loop,
                daemon=True,
                name="MouseHook-evdev",
            )
            self._evdev_thread.start()
        else:
            print("[MouseHook] evdev not available — button remapping disabled")

        return True

    def stop(self):
        self._running = False
        self.abort_button_gesture("stop")
        self._stop_hid_listener()
        self._hid_ready = False
        self._connected_device = None
        self._evdev_connected_device = None
        self._rescan_requested.set()
        self._evdev_wakeup.set()
        if self._evdev_thread:
            self._evdev_thread.join(timeout=2)
            self._evdev_thread = None
        self._cleanup_evdev()
        self._close_keyboard_devices()


MouseHook._platform_module = sys.modules[__name__]


__all__ = [
    "MouseHook",
    "HidGestureListener",
    "_select_mod",
    "_evdev_mod",
    "_InputDevice",
    "_UInput",
    "_ecodes",
    "_EVDEV_OK",
    "_LOGI_VENDOR",
]
