"""Source guards for the scroll engine's platform wiring.

The Windows hook cannot be imported off Windows, and the parts of the macOS and
Linux hooks these guards cover are shape rather than behaviour: that the curve
lives in one place, that the hook proc stays cheap, and that the duplicated
modifier handling is gone rather than merely bypassed.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _read(name):
    return (ROOT / "core" / name).read_text(encoding="utf-8")


MACOS = _read("mouse_hook_macos.py")
WINDOWS = _read("mouse_hook_windows.py")
LINUX = _read("mouse_hook_linux.py")
BASE = _read("mouse_hook_base.py")
HOOKS = {
    "macos": MACOS,
    "windows": WINDOWS,
    "linux": LINUX,
}


# ──────────────────────────────────────────────────────────────────────────────
# One curve, one modifier table
# ──────────────────────────────────────────────────────────────────────────────


class SharedImplementationTests(unittest.TestCase):
    def test_every_hook_uses_the_shared_engine(self):
        for name, source in HOOKS.items():
            with self.subTest(hook=name):
                self.assertIn("from core.scroll_engine import", source)

    def test_every_hook_uses_the_shared_modifier_table(self):
        for name, source in HOOKS.items():
            with self.subTest(hook=name):
                self.assertIn("resolve_wheel_action", source)
                self.assertIn("def modifier_state(", source + BASE)

    def test_no_hook_reimplements_the_curve(self):
        # The graph and the injector read the same function; a hook growing its
        # own copy is how they start disagreeing.
        for name, source in HOOKS.items():
            with self.subTest(hook=name):
                self.assertNotIn("def frame_weight", source)
                self.assertNotIn("def frame_profile", source)
                self.assertNotIn("brake_point", source)

    def test_the_old_per_platform_shift_handling_is_gone(self):
        self.assertNotIn("GetAsyncKeyState(VK_SHIFT)", WINDOWS)
        # The Quartz flag name survives in the shared bit table; what must
        # be gone is the tap testing it by hand.
        self.assertNotIn("flags & Quartz.kCGEventFlagMaskShift", MACOS)
        self.assertNotIn("def _shift_held", LINUX)

    def test_the_base_hook_owns_the_engine_lifecycle(self):
        self.assertIn("def configure_smooth_scroll", BASE)
        self.assertIn("def _make_scroll_emitter", BASE)
        self.assertIn("def _teardown_scroll_engine", BASE)


# ──────────────────────────────────────────────────────────────────────────────
# Windows: the hook proc has a watchdog
# ──────────────────────────────────────────────────────────────────────────────


class WindowsHookProcBudgetTests(unittest.TestCase):
    def _method(self, name):
        start = WINDOWS.index(f"    def {name}(")
        end = WINDOWS.index("\n    def ", start + 1)
        return WINDOWS[start:end]

    def _proc_call_path(self):
        # Everything the hook proc reaches on a wheel event, in one string.
        return "".join(self._method(name) for name in (
            "_low_level_handler_inner",
            "_handle_vwheel",
            "_push_smooth_wheel",
            "_post_mod_scroll",
            "_post_pending_mod_scroll",
        ))

    def test_nothing_on_the_proc_path_injects_synchronously(self):
        # A free spin is ~3000 events a second through a proc with a ~300 ms
        # watchdog. Injecting from here would also re-enter the hook.
        path = self._proc_call_path()
        self.assertIn("push_tick", path)
        self.assertNotIn("SendInput", path)
        self.assertNotIn("_inject_scroll_impl", path)

    def test_the_proc_itself_delegates_rather_than_deciding(self):
        proc = self._method("_low_level_handler_inner")
        self.assertIn("self._handle_vwheel(delta)", proc)
        self.assertNotIn("resolve_wheel_action", proc)

    def test_injection_is_deferred_to_a_posted_message_or_the_tick_thread(self):
        path = self._proc_call_path()
        self.assertIn("PostMessageW", path)

    def test_injection_happens_off_the_proc(self):
        self.assertIn("def _emit_smooth_scroll", WINDOWS)
        self.assertIn("_inject_scroll_impl(MOUSEEVENTF_WHEEL", WINDOWS)

    def test_the_modifier_poll_is_cached(self):
        self.assertIn("_MOD_CACHE_TTL_S", WINDOWS)
        self.assertIn("self._mod_cache", WINDOWS)

    def test_the_raised_timer_resolution_is_released(self):
        # timeBeginPeriod is system-wide; holding it while nothing scrolls
        # costs every process on the machine battery.
        self.assertIn("timeBeginPeriod", WINDOWS)
        self.assertIn("timeEndPeriod", WINDOWS)


# ──────────────────────────────────────────────────────────────────────────────
# macOS: markers and the trackpad gate
# ──────────────────────────────────────────────────────────────────────────────


class MacOSInjectionGuardTests(unittest.TestCase):
    def test_the_injected_marker_is_in_the_early_return_set(self):
        # Without this the tap re-enters on its own injected frames and the
        # glide feeds itself.
        start = MACOS.index("if source_marker in (")
        end = MACOS.index("):", start)
        self.assertIn("_SMOOTH_SCROLL_MARKER", MACOS[start:end])

    def test_the_marker_does_not_collide_with_the_others(self):
        markers = [line for line in MACOS.splitlines()
                   if line.startswith("_") and "_MARKER = 0x" in line]
        values = [line.split("= ")[1].strip() for line in markers]
        self.assertEqual(len(values), len(set(values)))

    def test_smooth_is_gated_on_both_trackpad_phases(self):
        self.assertIn("momentum_phase = ", MACOS)
        self.assertIn("from_trackpad = scroll_phase != 0 or momentum_phase != 0",
                      MACOS)

    def test_the_trackpad_gate_is_independent_of_ignore_trackpad(self):
        # Reading the phases only when ignore_trackpad is on would leave the
        # engine smoothing an already-continuous trackpad stream.
        phases = MACOS.index("scroll_phase = Quartz.CGEventGetIntegerValueField")
        gate = MACOS.index("if self.ignore_trackpad and from_trackpad:")
        self.assertLess(phases, gate)

    def test_the_autorelease_pool_is_per_frame(self):
        self.assertIn("def _scroll_frame_wrapper", MACOS)
        self.assertIn("objc.autorelease_pool", MACOS)


# ──────────────────────────────────────────────────────────────────────────────
# Linux: one write path, one lock
# ──────────────────────────────────────────────────────────────────────────────


class LinuxUinputGuardTests(unittest.TestCase):
    def test_there_is_exactly_one_uinput_write_call_site(self):
        # Two threads write now. A report reaching the kernel split across a
        # SYN_REPORT is a pointer jump, and a write racing close is an EBADF on
        # a descriptor the process may already have recycled.
        self.assertNotIn("self._uinput.write", LINUX)
        self.assertEqual(LINUX.count("device.write_event("), 1)
        self.assertEqual(LINUX.count("device.write("), 1)

    def test_the_write_path_holds_a_lock(self):
        self.assertIn("self._uinput_lock = threading.Lock()", LINUX)
        start = LINUX.index("def _uinput_write")
        end = LINUX.index("\n    def ", start + 1)
        self.assertIn("with self._uinput_lock:", LINUX[start:end])

    def test_close_takes_the_same_lock(self):
        start = LINUX.index("def _close_uinput")
        end = LINUX.index("\n    def ", start + 1)
        self.assertIn("with self._uinput_lock:", LINUX[start:end])

    def test_hi_res_capabilities_are_opt_in(self):
        self.assertIn("def _filtered_uinput_events(self, dev, *, hi_res=False)",
                      LINUX)

    def test_toggling_smooth_recreates_the_virtual_device(self):
        # uinput capabilities are fixed at creation, so the device has to be
        # rebuilt when the hi-res codes come or go.
        start = LINUX.index("def configure_smooth_scroll")
        end = LINUX.index("\n    def ", start + 1)
        body = LINUX[start:end]
        self.assertIn("_disable_evdev_remapping()", body)
        self.assertIn("_enable_evdev_remapping()", body)

    def test_the_modifier_read_is_cached(self):
        self.assertIn("_MOD_CACHE_TTL_S", LINUX)
        self.assertIn("def _read_modifier_mask", LINUX)

    def test_keyboards_are_accepted_on_any_modifier_not_just_shift(self):
        self.assertIn("_MODIFIER_KEY_BITS", LINUX)
        self.assertIn("KEY_LEFTCTRL", LINUX)
        self.assertIn("KEY_LEFTMETA", LINUX)


if __name__ == "__main__":
    unittest.main()
