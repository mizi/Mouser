"""Tests for the scroll settings bridge between QML and the config."""

import copy
import unittest
from unittest.mock import MagicMock, patch

from core.config import DEFAULT_CONFIG, SCROLL_TUNING_DEFAULTS
from ui.backend import Backend


def _make_backend(engine=None, cfg=None):
    loaded_config = copy.deepcopy(cfg or DEFAULT_CONFIG)
    with (
        patch("ui.backend.load_config", return_value=loaded_config),
        patch("ui.backend.supports_login_startup", return_value=False),
    ):
        return Backend(engine=engine)


def _engine():
    engine = MagicMock(name="engine")
    engine.smart_shift_supported = False
    # Left unset these come back as MagicMocks, which the device-layout
    # sync then tries to compare against an int.
    engine.connected_device = None
    engine.hid_features_ready = False
    engine.device_connected = False
    return engine


# ──────────────────────────────────────────────────────────────────────────────
# Properties
# ──────────────────────────────────────────────────────────────────────────────


PROPERTY_KEYS = {
    "vscrollDuration": "vscroll_duration",
    "vscrollBrakePoint": "vscroll_brake_point",
    "vscrollSpeed": "vscroll_speed",
    "vscrollAcceleration": "vscroll_acceleration",
    "vscrollSmoothness": "vscroll_smoothness",
    "vscrollSmooth": "vscroll_smooth",
    "hscrollSpeed": "hscroll_speed",
    "modScrollShiftHScroll": "mod_scroll_shift_hscroll",
    "modScrollCtrlZoom": "mod_scroll_ctrl_zoom",
    "modScrollCmdFast": "mod_scroll_cmd_fast",
    "modScrollInvertHScroll": "mod_scroll_invert_hscroll",
    "modScrollInvertZoom": "mod_scroll_invert_zoom",
    "modScrollGain": "mod_scroll_gain",
}

SETTERS = {
    "setVScrollDuration": ("vscroll_duration", 30),
    "setVScrollBrakePoint": ("vscroll_brake_point", 8),
    "setVScrollSpeed": ("vscroll_speed", 22),
    "setVScrollAcceleration": ("vscroll_acceleration", 40),
    "setVScrollSmoothness": ("vscroll_smoothness", 3),
    "setVScrollSmooth": ("vscroll_smooth", True),
    "setHScrollSpeed": ("hscroll_speed", 17),
    "setModScrollShiftHScroll": ("mod_scroll_shift_hscroll", False),
    "setModScrollCtrlZoom": ("mod_scroll_ctrl_zoom", True),
    "setModScrollCmdFast": ("mod_scroll_cmd_fast", True),
    "setModScrollInvertHScroll": ("mod_scroll_invert_hscroll", True),
    "setModScrollInvertZoom": ("mod_scroll_invert_zoom", True),
    "setModScrollGain": ("mod_scroll_gain", 6.5),
}


class ScrollPropertyTests(unittest.TestCase):
    def test_every_config_key_has_a_property(self):
        self.assertEqual(set(PROPERTY_KEYS.values()),
                         set(SCROLL_TUNING_DEFAULTS))

    def test_every_config_key_has_a_setter(self):
        self.assertEqual({key for key, _ in SETTERS.values()},
                         set(SCROLL_TUNING_DEFAULTS))

    def test_properties_read_the_shipped_defaults(self):
        backend = _make_backend()
        for prop, key in PROPERTY_KEYS.items():
            with self.subTest(prop=prop):
                self.assertEqual(getattr(backend, prop),
                                 SCROLL_TUNING_DEFAULTS[key])

    def test_properties_read_a_stored_value(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["settings"]["vscroll_speed"] = 33
        backend = _make_backend(cfg=cfg)

        self.assertEqual(backend.vscrollSpeed, 33)

    def test_the_gain_property_is_a_float(self):
        self.assertIsInstance(_make_backend().modScrollGain, float)


# ──────────────────────────────────────────────────────────────────────────────
# Setters
# ──────────────────────────────────────────────────────────────────────────────


class ScrollSetterTests(unittest.TestCase):
    def _backend(self):
        backend = _make_backend(engine=_engine())
        return backend

    def test_every_setter_persists_its_key(self):
        for setter, (key, value) in SETTERS.items():
            with self.subTest(setter=setter):
                backend = self._backend()
                with patch("ui.backend.save_config") as save:
                    getattr(backend, setter)(value)
                self.assertEqual(backend._cfg["settings"][key], value)
                save.assert_called_once()

    def test_every_setter_emits_the_scroll_signal(self):
        for setter, (_, value) in SETTERS.items():
            with self.subTest(setter=setter):
                backend = self._backend()
                seen = []
                backend.scrollSettingsChanged.connect(lambda: seen.append(True))
                with patch("ui.backend.save_config"):
                    getattr(backend, setter)(value)
                self.assertEqual(seen, [True])

    def test_an_unchanged_value_is_a_no_op(self):
        backend = self._backend()
        seen = []
        backend.scrollSettingsChanged.connect(lambda: seen.append(True))
        with patch("ui.backend.save_config") as save:
            backend.setVScrollSpeed(SCROLL_TUNING_DEFAULTS["vscroll_speed"])

        save.assert_not_called()
        self.assertEqual(seen, [])

    def test_a_change_pushes_to_the_engine_exactly_once(self):
        backend = self._backend()
        with patch("ui.backend.save_config"):
            backend.setVScrollSpeed(31)

        backend._engine.apply_scroll_tuning.assert_called_once_with(backend._cfg)

    def test_a_change_never_reloads_the_mappings(self):
        # reload_mappings rebuilds every button callback and re-registers the
        # hook; a slider fires this every 400 ms while it is dragged.
        backend = self._backend()
        with patch("ui.backend.save_config"):
            backend.setVScrollSpeed(31)

        backend._engine.reload_mappings.assert_not_called()

    def test_values_are_clamped_at_both_ends(self):
        backend = self._backend()
        with patch("ui.backend.save_config"):
            backend.setVScrollDuration(9999)
            backend.setVScrollSpeed(-40)
            backend.setModScrollGain(1000.0)

        self.assertEqual(backend.vscrollDuration, 60)
        self.assertEqual(backend.vscrollSpeed, 1)
        self.assertEqual(backend.modScrollGain, 10.0)

    def test_the_brake_point_follows_a_lowered_duration(self):
        backend = self._backend()
        with patch("ui.backend.save_config"):
            backend.setVScrollDuration(40)
            backend.setVScrollBrakePoint(12)
            backend.setVScrollDuration(5)

        self.assertEqual(backend.vscrollBrakePoint, 5)

    def test_raising_the_duration_leaves_the_brake_point_alone(self):
        backend = self._backend()
        with patch("ui.backend.save_config"):
            backend.setVScrollBrakePoint(6)
            backend.setVScrollDuration(50)

        self.assertEqual(backend.vscrollBrakePoint, 6)

    def test_a_fractional_gain_survives_the_round_trip(self):
        backend = self._backend()
        with patch("ui.backend.save_config"):
            backend.setModScrollGain(4.5)

        self.assertAlmostEqual(backend.modScrollGain, 4.5)

    def test_garbage_falls_back_to_the_default(self):
        backend = self._backend()
        with patch("ui.backend.save_config"):
            backend.setModScrollGain(float("nan"))

        self.assertAlmostEqual(backend.modScrollGain, 3.2)

    def test_a_backend_without_an_engine_still_persists(self):
        backend = _make_backend()
        with patch("ui.backend.save_config"):
            backend.setVScrollSpeed(28)

        self.assertEqual(backend.vscrollSpeed, 28)


# ──────────────────────────────────────────────────────────────────────────────
# Graph samples
# ──────────────────────────────────────────────────────────────────────────────


class ScrollCurveSampleTests(unittest.TestCase):
    def test_the_default_curve_has_one_sample_per_frame_plus_the_zero(self):
        samples = _make_backend().scrollCurveSamples(12, 4, 10, 7, 0)

        self.assertEqual(len(samples), 13)
        self.assertEqual(samples[-1]["speed"], 0.0)

    def test_the_distance_series_is_monotonic(self):
        samples = _make_backend().scrollCurveSamples(12, 4, 10, 7, 0)
        totals = [s["total"] for s in samples]

        self.assertEqual(totals, sorted(totals))

    def test_the_degenerate_curve_stays_finite(self):
        # Duration 2 with the brake already at 2 is reachable by dragging the
        # duration slider down, and is a divide by zero without its guard.
        samples = _make_backend().scrollCurveSamples(2, 2, 1, 0, 0)

        for sample in samples:
            self.assertEqual(sample["speed"], sample["speed"])
            self.assertEqual(sample["total"], sample["total"])

    def test_acceleration_only_moves_the_boosted_series(self):
        backend = _make_backend()
        plain = backend.scrollCurveSamples(12, 4, 10, 0, 0)
        boosted = backend.scrollCurveSamples(12, 4, 10, 60, 0)

        self.assertEqual([s["speed"] for s in plain],
                         [s["speed"] for s in boosted])
        self.assertGreater(boosted[0]["boosted"], plain[0]["boosted"])

    def test_smoothing_lengthens_the_sample_series(self):
        backend = _make_backend()
        sharp = backend.scrollCurveSamples(12, 4, 10, 0, 0)
        soft = backend.scrollCurveSamples(12, 4, 10, 0, 5)

        self.assertGreater(len(soft), len(sharp))



# ──────────────────────────────────────────────────────────────────────────────
# Per-app Shift+wheel
# ──────────────────────────────────────────────────────────────────────────────


def _cfg_with_app_profile(**overrides):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["profiles"]["project"] = {
        "label": "MS Project",
        "apps": ["WINPROJ.EXE"],
        "mappings": {},
        "button_haptic": {},
        "scroll_overrides": dict(overrides),
    }
    return cfg


class ProfileShiftHScrollTests(unittest.TestCase):
    def test_app_profiles_are_listed_and_default_is_not(self):
        backend = _make_backend(cfg=_cfg_with_app_profile())

        names = [row["name"] for row in backend.profileShiftHScroll]

        self.assertEqual(names, ["project"])

    def test_a_profile_without_an_override_inherits(self):
        backend = _make_backend(cfg=_cfg_with_app_profile())

        self.assertEqual(backend.profileShiftHScroll[0]["mode"], "inherit")

    def test_a_stored_override_reads_back(self):
        backend = _make_backend(cfg=_cfg_with_app_profile(
            mod_scroll_shift_hscroll=False))

        self.assertEqual(backend.profileShiftHScroll[0]["mode"], "off")

    def test_setting_off_stores_an_override_and_pushes(self):
        backend = _make_backend(engine=_engine(), cfg=_cfg_with_app_profile())
        with patch("ui.backend.save_config") as save:
            backend.setProfileShiftHScroll("project", "off")

        overrides = backend._cfg["profiles"]["project"]["scroll_overrides"]
        self.assertIs(overrides["mod_scroll_shift_hscroll"], False)
        save.assert_called_once()
        backend._engine.apply_scroll_tuning.assert_called_once_with(backend._cfg)

    def test_inherit_removes_the_override(self):
        backend = _make_backend(engine=_engine(), cfg=_cfg_with_app_profile(
            mod_scroll_shift_hscroll=False))
        with patch("ui.backend.save_config"):
            backend.setProfileShiftHScroll("project", "inherit")

        self.assertEqual(
            backend._cfg["profiles"]["project"]["scroll_overrides"], {})

    def test_an_unchanged_mode_is_a_no_op(self):
        backend = _make_backend(engine=_engine(), cfg=_cfg_with_app_profile())
        with patch("ui.backend.save_config") as save:
            backend.setProfileShiftHScroll("project", "inherit")

        save.assert_not_called()

    def test_unknown_profiles_and_modes_are_ignored(self):
        backend = _make_backend(engine=_engine(), cfg=_cfg_with_app_profile())
        with patch("ui.backend.save_config") as save:
            backend.setProfileShiftHScroll("nope", "off")
            backend.setProfileShiftHScroll("project", "sideways")

        save.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Backend and engine, wired together
# ──────────────────────────────────────────────────────────────────────────────


class _RecordingHook:
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
        self.pushes = []

    def set_debug_callback(self, cb): pass
    def set_gesture_callback(self, cb): pass
    def set_status_callback(self, cb): pass
    def set_connection_change_callback(self, cb): pass
    def set_battery_notify_callback(self, cb): pass
    def set_profile_change_callback(self, cb): pass
    def configure_gestures(self, **kwargs): pass
    def configure_wheel_multipliers(self, v, h): return None
    def block(self, event_type): pass
    def register(self, event_type, callback): pass
    def reset_bindings(self): pass
    def start(self): pass
    def stop(self): pass

    def configure_smooth_scroll(self, settings):
        self.pushes.append(settings)


class _QuietAppDetector:
    def __init__(self, callback): pass
    def start(self): pass
    def stop(self): pass


class EndToEndScrollTuningTests(unittest.TestCase):
    def _wire(self, cfg):
        from core.engine import Engine

        # Each side gets its own copy, exactly as in the running app: the
        # engine and the backend both call load_config() independently.
        with (
            patch("core.engine.MouseHook", _RecordingHook),
            patch("core.engine.AppDetector", _QuietAppDetector),
            patch("core.engine.load_config", return_value=copy.deepcopy(cfg)),
        ):
            engine = Engine()
        backend = _make_backend(engine=engine, cfg=cfg)
        self.assertIsNot(engine.cfg, backend._cfg)
        return engine, backend

    def test_a_slider_change_reaches_the_hook(self):
        engine, backend = self._wire(copy.deepcopy(DEFAULT_CONFIG))
        with patch("ui.backend.save_config"):
            backend.setVScrollSpeed(37)

        self.assertEqual(engine.hook.pushes[-1]["vscroll_speed"], 37)

    def test_turning_smooth_on_reaches_the_hook(self):
        engine, backend = self._wire(copy.deepcopy(DEFAULT_CONFIG))
        with patch("ui.backend.save_config"):
            backend.setVScrollSmooth(True)

        self.assertTrue(engine.hook.pushes[-1]["vscroll_smooth"])

    def test_a_per_app_override_applies_while_that_app_is_active(self):
        cfg = _cfg_with_app_profile()
        engine, backend = self._wire(cfg)
        with patch("ui.backend.save_config"):
            backend.setProfileShiftHScroll("project", "off")
        self.assertTrue(engine.hook.pushes[-1]["mod_scroll_shift_hscroll"])

        engine._switch_profile("project")

        self.assertFalse(engine.hook.pushes[-1]["mod_scroll_shift_hscroll"])

    def test_leaving_the_app_restores_the_global_setting(self):
        cfg = _cfg_with_app_profile(mod_scroll_shift_hscroll=False)
        engine, _ = self._wire(cfg)
        engine._switch_profile("project")
        engine._switch_profile("default")

        self.assertTrue(engine.hook.pushes[-1]["mod_scroll_shift_hscroll"])

    def test_adopting_scroll_settings_leaves_the_rest_of_the_engine_config(self):
        engine, backend = self._wire(copy.deepcopy(DEFAULT_CONFIG))
        engine.cfg["settings"]["dpi"] = 1600
        backend._cfg["settings"]["dpi"] = 400
        with patch("ui.backend.save_config"):
            backend.setVScrollSpeed(12)

        self.assertEqual(engine.cfg["settings"]["dpi"], 1600)


if __name__ == "__main__":
    unittest.main()
