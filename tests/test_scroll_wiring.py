"""Tests for the scroll engine's hook and Engine wiring."""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.config import DEFAULT_CONFIG
from core.mouse_hook_base import BaseMouseHook
from core.mouse_hook_contract import MouseHookLike
from core.scroll_engine import ScrollConfig


def _settings(**overrides):
    settings = copy.deepcopy(DEFAULT_CONFIG["settings"])
    settings.update(overrides)
    return settings


class _EmittingHook(BaseMouseHook):
    def __init__(self):
        super().__init__()
        self.emitted = []

    def _make_scroll_emitter(self):
        return lambda dy, dx: self.emitted.append((dy, dx))


# ──────────────────────────────────────────────────────────────────────────────
# BaseMouseHook surface
# ──────────────────────────────────────────────────────────────────────────────


class SmoothScrollSurfaceTests(unittest.TestCase):
    def tearDown(self):
        for hook in getattr(self, "_hooks", ()):
            hook.configure_smooth_scroll(None)

    def _hook(self, cls=BaseMouseHook):
        hook = cls()
        self._hooks = getattr(self, "_hooks", [])
        self._hooks.append(hook)
        return hook

    def test_the_contract_carries_the_new_methods(self):
        for name in ("configure_smooth_scroll", "modifier_state"):
            self.assertIn(name, MouseHookLike.__protocol_attrs__, name)

    def test_the_base_hook_supplies_every_contract_attribute_it_owns(self):
        # start/stop are the platform subclass's; everything else, the new
        # scroll methods included, has to be present on the base or the
        # real hooks fail the contract check on every platform.
        hook = self._hook()
        missing = {name for name in MouseHookLike.__protocol_attrs__
                   if not hasattr(hook, name)}

        self.assertEqual(missing, {"start", "stop"})

    def test_smooth_off_creates_no_engine(self):
        hook = self._hook()
        hook.configure_smooth_scroll(_settings(vscroll_smooth=False))

        self.assertIsNone(hook._scroll_driver)

    def test_smooth_on_creates_an_engine(self):
        hook = self._hook()
        hook.configure_smooth_scroll(_settings(vscroll_smooth=True))

        self.assertIsNotNone(hook._scroll_engine)
        self.assertTrue(hook._scroll_engine.config.enabled)

    def test_a_hook_that_cannot_inject_stays_in_pass_through(self):
        # Swallowing wheel events with nothing to replace them would leave the
        # wheel dead, so a build with no injector must never arm the driver.
        hook = self._hook()
        hook.configure_smooth_scroll(_settings(vscroll_smooth=True))

        self.assertIsNone(hook._make_scroll_emitter())
        self.assertIsNone(hook._scroll_driver)

    def test_an_injecting_hook_starts_the_driver(self):
        hook = self._hook(_EmittingHook)
        hook.configure_smooth_scroll(_settings(vscroll_smooth=True))

        self.assertIsNotNone(hook._scroll_driver)
        self.assertTrue(hook._scroll_driver.running)

    def test_turning_smooth_off_stops_the_driver(self):
        hook = self._hook(_EmittingHook)
        hook.configure_smooth_scroll(_settings(vscroll_smooth=True))
        hook.configure_smooth_scroll(_settings(vscroll_smooth=False))

        self.assertIsNone(hook._scroll_driver)

    def test_none_tears_everything_down(self):
        hook = self._hook(_EmittingHook)
        hook.configure_smooth_scroll(_settings(vscroll_smooth=True))
        hook.configure_smooth_scroll(None)

        self.assertIsNone(hook._scroll_driver)
        self.assertIsNone(hook._scroll_settings)
        self.assertIsNone(hook._mod_scroll)

    def test_modifier_translation_survives_smooth_being_off(self):
        # Shift+wheel pans whether or not the software engine is running.
        hook = self._hook()
        hook.configure_smooth_scroll(_settings(vscroll_smooth=False))

        self.assertIsNotNone(hook._mod_scroll)
        self.assertTrue(hook._mod_scroll.mod_shift_hscroll)

    def test_retuning_keeps_the_same_engine_and_driver(self):
        hook = self._hook(_EmittingHook)
        hook.configure_smooth_scroll(_settings(vscroll_smooth=True,
                                               vscroll_speed=10))
        engine = hook._scroll_engine
        driver = hook._scroll_driver
        hook.configure_smooth_scroll(_settings(vscroll_smooth=True,
                                               vscroll_speed=30))

        self.assertIs(hook._scroll_engine, engine)
        self.assertIs(hook._scroll_driver, driver)
        self.assertEqual(engine.config.v.speed, 30)

    def test_the_default_modifier_state_is_empty(self):
        self.assertEqual(self._hook().modifier_state(), 0)


# ──────────────────────────────────────────────────────────────────────────────
# Firmware invert hand-off
# ──────────────────────────────────────────────────────────────────────────────


class NativeInvertHandoffTests(unittest.TestCase):
    def tearDown(self):
        for hook in getattr(self, "_hooks", ()):
            hook.configure_smooth_scroll(None)

    def _hook(self):
        hook = _EmittingHook()
        self._hooks = getattr(self, "_hooks", [])
        self._hooks.append(hook)
        return hook

    def test_software_invert_applies_when_the_firmware_is_not_inverting(self):
        hook = self._hook()
        hook.configure_smooth_scroll(_settings(vscroll_smooth=True,
                                               invert_vscroll=True))

        self.assertTrue(hook._scroll_engine.config.invert_v)

    def test_the_firmware_taking_over_suppresses_software_invert(self):
        hook = self._hook()
        hook.configure_smooth_scroll(_settings(vscroll_smooth=True,
                                               invert_vscroll=True))
        hook.wheel_native_invert_active = True

        self.assertFalse(hook._scroll_engine.config.invert_v)

    def test_the_firmware_giving_up_restores_software_invert(self):
        hook = self._hook()
        hook.wheel_native_invert_active = True
        hook.configure_smooth_scroll(_settings(vscroll_smooth=True,
                                               invert_vscroll=True))
        self.assertFalse(hook._scroll_engine.config.invert_v)

        hook.wheel_native_invert_active = False

        self.assertTrue(hook._scroll_engine.config.invert_v)

    def test_writing_the_same_value_does_not_rebuild(self):
        hook = self._hook()
        hook.configure_smooth_scroll(_settings(vscroll_smooth=True))
        calls = []
        hook._on_wheel_invert_mode_changed = lambda: calls.append(True)
        hook.wheel_native_invert_active = False

        self.assertEqual(calls, [])

    def test_the_flag_is_inert_before_any_scroll_config_arrives(self):
        hook = self._hook()
        hook.wheel_native_invert_active = True

        self.assertIsNone(hook._scroll_engine)


# ──────────────────────────────────────────────────────────────────────────────
# Engine wiring
# ──────────────────────────────────────────────────────────────────────────────


class _ScrollFakeHook:
    def __init__(self):
        self.invert_vscroll = False
        self.invert_hscroll = False
        self.debug_mode = False
        self.connected_device = None
        self.device_connected = False
        self.divert_mode_shift = False
        self.divert_dpi_switch = False
        self.wheel_native_invert_active = False
        self.wheel_divert_active = False
        self.ignore_trackpad = True
        self._hid_gesture = None
        self._blocked_events = set()
        self.scroll_pushes = []
        self.passthrough = None

    def set_debug_callback(self, cb): pass
    def set_gesture_callback(self, cb): pass
    def set_status_callback(self, cb): pass
    def set_connection_change_callback(self, cb): pass
    def set_battery_notify_callback(self, cb): pass
    def configure_gestures(self, **kwargs): pass
    def configure_wheel_multipliers(self, v, h): return None
    def block(self, event_type): pass
    def register(self, event_type, callback): pass
    def reset_bindings(self): pass
    def start(self): pass
    def stop(self): pass

    def configure_smooth_scroll(self, settings):
        self.scroll_pushes.append(settings)

    def set_ui_passthrough(self, enabled):
        self.passthrough = enabled


class _ScrollFakeAppDetector:
    def __init__(self, callback):
        self.callback = callback

    def start(self): pass
    def stop(self): pass


class EngineScrollTuningTests(unittest.TestCase):
    def _make_engine(self, **overrides):
        from core.engine import Engine

        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["settings"].update(overrides)
        with (
            patch("core.engine.MouseHook", _ScrollFakeHook),
            patch("core.engine.AppDetector", _ScrollFakeAppDetector),
            patch("core.engine.load_config", return_value=cfg),
        ):
            return Engine()

    def test_setup_pushes_the_scroll_settings_to_the_hook(self):
        engine = self._make_engine(vscroll_smooth=True, vscroll_speed=22)

        self.assertTrue(engine.hook.scroll_pushes)
        self.assertEqual(engine.hook.scroll_pushes[-1]["vscroll_speed"], 22)

    def test_apply_scroll_tuning_re_pushes_the_current_settings(self):
        engine = self._make_engine()
        engine.hook.scroll_pushes.clear()
        saved = copy.deepcopy(engine.cfg)
        saved["settings"]["vscroll_speed"] = 31
        engine.apply_scroll_tuning(saved)

        self.assertEqual(len(engine.hook.scroll_pushes), 1)
        self.assertEqual(engine.hook.scroll_pushes[-1]["vscroll_speed"], 31)

    def test_apply_scroll_tuning_does_not_reload_mappings(self):
        # reload_mappings rebuilds every button callback and re-registers the
        # hook. A slider commits every 400 ms while it is dragged.
        engine = self._make_engine()
        with patch.object(engine, "_setup_hooks") as setup:
            engine.apply_scroll_tuning(copy.deepcopy(engine.cfg))

        setup.assert_not_called()

    def test_disabling_mouser_stops_the_injector(self):
        engine = self._make_engine(vscroll_smooth=True)
        engine.hook.scroll_pushes.clear()
        engine.set_enabled(False)

        self.assertIsNone(engine.hook.scroll_pushes[-1])

    def test_re_enabling_mouser_restores_the_injector(self):
        engine = self._make_engine(vscroll_smooth=True)
        engine.set_enabled(False)
        engine.set_enabled(True)

        self.assertIsNotNone(engine.hook.scroll_pushes[-1])

    def test_ui_passthrough_stops_the_injector(self):
        engine = self._make_engine(vscroll_smooth=True)
        engine.set_ui_passthrough(True)

        self.assertIsNone(engine.hook.scroll_pushes[-1])
        self.assertTrue(engine.hook.passthrough)

    def test_leaving_ui_passthrough_restores_the_injector(self):
        engine = self._make_engine(vscroll_smooth=True)
        engine.set_ui_passthrough(True)
        engine.set_ui_passthrough(False)

        self.assertIsNotNone(engine.hook.scroll_pushes[-1])

    def test_with_no_source_the_saved_file_is_read(self):
        engine = self._make_engine()
        saved = copy.deepcopy(engine.cfg)
        saved["settings"]["vscroll_speed"] = 44
        with patch("core.engine.load_config", return_value=saved) as load:
            engine.apply_scroll_tuning()

        load.assert_called_once_with()
        self.assertEqual(engine.hook.scroll_pushes[-1]["vscroll_speed"], 44)

    def test_a_hook_without_the_method_is_skipped(self):
        engine = self._make_engine()
        engine.hook = SimpleNamespace()
        try:
            engine.apply_scroll_tuning(copy.deepcopy(engine.cfg))
        except AttributeError:
            self.fail("apply_scroll_tuning must tolerate a hook without it")


class ScrollConfigFromDefaultsTests(unittest.TestCase):
    def test_the_shipped_defaults_build_a_valid_config(self):
        config = ScrollConfig.from_settings(DEFAULT_CONFIG["settings"])

        self.assertFalse(config.enabled)
        self.assertEqual(config.v.duration, 12)
        self.assertEqual(config.v.brake_point, 4)
        self.assertEqual(config.v.speed, 10)
        self.assertAlmostEqual(config.mod_gain, 3.2)


if __name__ == "__main__":
    unittest.main()
