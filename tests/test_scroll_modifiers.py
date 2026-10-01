"""Tests for core.scroll_modifiers — the modifier+wheel translation table."""

import math
import unittest

from core.scroll_engine import (
    MOD_ALT as ALT_NAME,
    MOD_CMD,
    MOD_CTRL,
    MOD_FAST,
    MOD_HSCROLL,
    MOD_NONE,
    MOD_PASSTHROUGH,
    MOD_SHIFT,
    MOD_ZOOM,
)
from core.scroll_modifiers import (
    MOD_ALT,
    MOD_CTRL_BIT,
    MOD_META,
    MOD_SHIFT_BIT,
    ModScrollSettings,
    ScrollAccumulator,
    WheelPlan,
    clamp_gain,
    modifier_names,
    resolve_wheel_action,
)

_ALL_BITS = (MOD_SHIFT_BIT, MOD_CTRL_BIT, MOD_ALT, MOD_META)


def _settings(**overrides):
    base = {
        "mod_shift_hscroll": True,
        "mod_ctrl_zoom": True,
        "mod_cmd_fast": True,
    }
    base.update(overrides)
    return ModScrollSettings(**base)


# ──────────────────────────────────────────────────────────────────────────────
# Bitmask translation
# ──────────────────────────────────────────────────────────────────────────────


class ModifierNameTests(unittest.TestCase):
    def test_each_bit_maps_to_its_engine_name(self):
        self.assertEqual(modifier_names(MOD_SHIFT_BIT), {MOD_SHIFT})
        self.assertEqual(modifier_names(MOD_CTRL_BIT), {MOD_CTRL})
        self.assertEqual(modifier_names(MOD_META), {MOD_CMD})

    def test_alt_is_reported_so_it_can_be_passed_through(self):
        self.assertEqual(modifier_names(MOD_ALT), {ALT_NAME})
        self.assertEqual(modifier_names(MOD_ALT | MOD_SHIFT_BIT),
                         {MOD_SHIFT, ALT_NAME})

    def test_an_empty_mask_is_empty(self):
        self.assertEqual(modifier_names(0), frozenset())

    def test_a_garbage_mask_is_empty(self):
        for mask in (None, "shift", object()):
            self.assertEqual(modifier_names(mask), frozenset())

    def test_the_bits_do_not_overlap(self):
        self.assertEqual(len(set(_ALL_BITS)), 4)
        self.assertEqual(sum(_ALL_BITS), MOD_SHIFT_BIT | MOD_CTRL_BIT
                         | MOD_ALT | MOD_META)


# ──────────────────────────────────────────────────────────────────────────────
# The full truth table
# ──────────────────────────────────────────────────────────────────────────────


class WheelPlanTruthTableTests(unittest.TestCase):
    def _mode(self, mask, **overrides):
        return resolve_wheel_action(mask, _settings(**overrides)).mode

    def test_all_sixteen_combinations_resolve(self):
        expected = {
            0: MOD_NONE,
            MOD_ALT: MOD_PASSTHROUGH,
            MOD_SHIFT_BIT: MOD_HSCROLL,
            MOD_SHIFT_BIT | MOD_ALT: MOD_PASSTHROUGH,
            MOD_CTRL_BIT: MOD_ZOOM,
            MOD_CTRL_BIT | MOD_ALT: MOD_PASSTHROUGH,
            MOD_META: MOD_FAST,
            MOD_META | MOD_ALT: MOD_PASSTHROUGH,
            MOD_SHIFT_BIT | MOD_CTRL_BIT: MOD_PASSTHROUGH,
            MOD_SHIFT_BIT | MOD_CTRL_BIT | MOD_ALT: MOD_PASSTHROUGH,
            MOD_SHIFT_BIT | MOD_META: MOD_PASSTHROUGH,
            MOD_SHIFT_BIT | MOD_META | MOD_ALT: MOD_PASSTHROUGH,
            MOD_CTRL_BIT | MOD_META: MOD_PASSTHROUGH,
            MOD_CTRL_BIT | MOD_META | MOD_ALT: MOD_PASSTHROUGH,
            MOD_SHIFT_BIT | MOD_CTRL_BIT | MOD_META: MOD_PASSTHROUGH,
            MOD_SHIFT_BIT | MOD_CTRL_BIT | MOD_META | MOD_ALT: MOD_PASSTHROUGH,
        }
        self.assertEqual(len(expected), 16)
        for mask, mode in expected.items():
            self.assertEqual(self._mode(mask), mode, mask)

    def test_a_disabled_modifier_leaves_the_wheel_alone(self):
        self.assertEqual(self._mode(MOD_SHIFT_BIT, mod_shift_hscroll=False),
                         MOD_NONE)
        self.assertEqual(self._mode(MOD_CTRL_BIT, mod_ctrl_zoom=False),
                         MOD_NONE)
        self.assertEqual(self._mode(MOD_META, mod_cmd_fast=False), MOD_NONE)

    def test_two_held_modifiers_pass_through_even_when_one_is_disabled(self):
        # Ctrl+Shift+wheel is an application's binding to make. Gating on the
        # enabled ones alone would turn it into a pan the moment Ctrl-zoom is
        # switched off.
        mode = self._mode(MOD_SHIFT_BIT | MOD_CTRL_BIT, mod_ctrl_zoom=False)
        self.assertEqual(mode, MOD_PASSTHROUGH)

    def test_a_no_op_plan_leaves_the_event_untouched(self):
        plan = resolve_wheel_action(0, _settings())
        self.assertTrue(plan.is_noop)
        self.assertEqual(plan.strip_mods, 0)
        self.assertEqual(plan.v_scale, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# Which modifiers each mode strips
# ──────────────────────────────────────────────────────────────────────────────


class ModifierStrippingTests(unittest.TestCase):
    def test_shift_hscroll_strips_shift(self):
        plan = resolve_wheel_action(MOD_SHIFT_BIT, _settings())
        self.assertEqual(plan.strip_mods, MOD_SHIFT_BIT)

    def test_cmd_fast_strips_meta(self):
        plan = resolve_wheel_action(MOD_META, _settings())
        self.assertEqual(plan.strip_mods, MOD_META)

    def test_ctrl_zoom_strips_nothing(self):
        # The application reads the physical Ctrl state to decide it is a zoom,
        # so clearing the flag turns the zoom back into a scroll.
        plan = resolve_wheel_action(MOD_CTRL_BIT, _settings())
        self.assertEqual(plan.strip_mods, 0)

    def test_alt_with_anything_is_a_pass_through(self):
        for mask in (0, MOD_SHIFT_BIT, MOD_CTRL_BIT, MOD_META):
            plan = resolve_wheel_action(mask | MOD_ALT, _settings())
            self.assertTrue(plan.is_noop, mask)

    def test_no_mode_ever_strips_alt(self):
        for mask in (0, MOD_SHIFT_BIT, MOD_CTRL_BIT, MOD_META):
            plan = resolve_wheel_action(mask | MOD_ALT, _settings())
            self.assertFalse(plan.strip_mods & MOD_ALT, mask)


# ──────────────────────────────────────────────────────────────────────────────
# Scaling and direction
# ──────────────────────────────────────────────────────────────────────────────


class WheelScalingTests(unittest.TestCase):
    def test_shift_moves_the_delta_onto_the_horizontal_axis(self):
        plan = resolve_wheel_action(MOD_SHIFT_BIT, _settings())
        self.assertEqual(plan.v_scale, 0.0)
        self.assertEqual(plan.h_scale, 1.0)

    def test_the_modified_pan_has_its_own_invert(self):
        plan = resolve_wheel_action(MOD_SHIFT_BIT,
                                    _settings(invert_mod_h=True))
        self.assertEqual(plan.h_scale, -1.0)

    def test_the_plain_hscroll_invert_does_not_reach_the_modified_pan(self):
        # The two settings are independent, which is what keeps a firmware
        # inverting device from flipping the modified pan as a side effect.
        plan = resolve_wheel_action(MOD_SHIFT_BIT,
                                    _settings(invert_mod_h=False))
        self.assertEqual(plan.h_scale, 1.0)

    def test_zoom_scales_by_the_gain(self):
        plan = resolve_wheel_action(MOD_CTRL_BIT, _settings(mod_gain=4.0))
        self.assertEqual(plan.v_scale, 4.0)

    def test_zoom_invert_flips_the_gain(self):
        plan = resolve_wheel_action(MOD_CTRL_BIT,
                                    _settings(mod_gain=4.0, invert_zoom=True))
        self.assertEqual(plan.v_scale, -4.0)

    def test_fast_scroll_scales_by_the_gain(self):
        plan = resolve_wheel_action(MOD_META, _settings(mod_gain=2.5))
        self.assertEqual(plan.v_scale, 2.5)

    def test_zoom_invert_does_not_reach_fast_scroll(self):
        plan = resolve_wheel_action(MOD_META,
                                    _settings(mod_gain=2.5, invert_zoom=True))
        self.assertEqual(plan.v_scale, 2.5)


# ──────────────────────────────────────────────────────────────────────────────
# Gain clamping
# ──────────────────────────────────────────────────────────────────────────────


class GainClampTests(unittest.TestCase):
    def test_in_range_values_pass_through(self):
        self.assertAlmostEqual(clamp_gain(3.2), 3.2)
        self.assertAlmostEqual(clamp_gain(0.1), 0.1)
        self.assertAlmostEqual(clamp_gain(10.0), 10.0)

    def test_out_of_range_values_are_clamped(self):
        self.assertEqual(clamp_gain(-5), 0.1)
        self.assertEqual(clamp_gain(1000), 10.0)

    def test_non_numbers_fall_back_to_the_default(self):
        for value in (None, "x", object(), [1]):
            self.assertAlmostEqual(clamp_gain(value), 3.2)

    def test_nan_and_infinity_fall_back_to_the_default(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            self.assertAlmostEqual(clamp_gain(value), 3.2)

    def test_an_integer_gain_is_accepted(self):
        self.assertAlmostEqual(clamp_gain(4), 4.0)

    def test_the_settings_holder_clamps_on_construction(self):
        self.assertAlmostEqual(_settings(mod_gain=99).mod_gain, 10.0)

    def test_from_settings_reads_the_config_keys(self):
        settings = ModScrollSettings.from_settings({
            "mod_scroll_shift_hscroll": False,
            "mod_scroll_ctrl_zoom": True,
            "mod_scroll_cmd_fast": True,
            "mod_scroll_invert_hscroll": True,
            "mod_scroll_invert_zoom": True,
            "mod_scroll_gain": 5.5,
        })
        self.assertFalse(settings.mod_shift_hscroll)
        self.assertTrue(settings.mod_ctrl_zoom)
        self.assertTrue(settings.mod_cmd_fast)
        self.assertTrue(settings.invert_mod_h)
        self.assertTrue(settings.invert_zoom)
        self.assertAlmostEqual(settings.mod_gain, 5.5)

    def test_from_settings_survives_an_empty_dict(self):
        settings = ModScrollSettings.from_settings({})
        self.assertTrue(settings.mod_shift_hscroll)
        self.assertFalse(settings.mod_ctrl_zoom)

    def test_the_settings_holder_is_immutable(self):
        with self.assertRaises(AttributeError):
            _settings().mod_gain = 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Fractional carry
# ──────────────────────────────────────────────────────────────────────────────


class ScrollAccumulatorTests(unittest.TestCase):
    def test_a_hires_burst_keeps_its_fraction(self):
        accumulator = ScrollAccumulator()
        emitted = [accumulator.feed(8, 3.2) for _ in range(5)]
        self.assertEqual(sum(emitted), 128)

    def test_no_drift_over_a_thousand_events(self):
        accumulator = ScrollAccumulator()
        total = sum(accumulator.feed(1, 0.1) for _ in range(1000))
        self.assertEqual(total, 100)

    def test_a_small_gain_moves_the_wheel_at_the_rate_it_says(self):
        # A gain of 0.1 means one unit every tenth detent. Forcing a minimum
        # step of 1 would make every gain below 1.0 behave like 1.0.
        accumulator = ScrollAccumulator()
        emitted = [accumulator.feed(1, 0.1) for _ in range(10)]
        self.assertEqual(emitted, [0] * 9 + [1])

    def test_min_step_is_available_for_a_caller_that_needs_it(self):
        accumulator = ScrollAccumulator()
        self.assertEqual(accumulator.feed(1, 0.1, min_step=1), 1)

    def test_min_step_still_carries_the_debt(self):
        accumulator = ScrollAccumulator()
        accumulator.feed(1, 0.1, min_step=1)
        self.assertLess(accumulator.residue, 0.0)

    def test_direction_is_preserved(self):
        accumulator = ScrollAccumulator()
        self.assertEqual(sum(accumulator.feed(-8, 3.2) for _ in range(5)), -128)

    def test_a_reversal_does_not_leak_a_unit(self):
        accumulator = ScrollAccumulator()
        accumulator.feed(1, 0.6)
        accumulator.feed(-1, 0.6)
        self.assertAlmostEqual(accumulator.residue, 0.0)

    def test_a_zero_delta_emits_nothing(self):
        accumulator = ScrollAccumulator()
        self.assertEqual(accumulator.feed(0, 3.2), 0)

    def test_a_zero_scale_emits_nothing(self):
        accumulator = ScrollAccumulator()
        self.assertEqual(accumulator.feed(8, 0.0), 0)

    def test_non_finite_input_is_dropped(self):
        accumulator = ScrollAccumulator()
        self.assertEqual(accumulator.feed(float("nan"), 3.2), 0)
        self.assertEqual(accumulator.feed(8, float("inf")), 0)

    def test_garbage_input_is_dropped(self):
        accumulator = ScrollAccumulator()
        self.assertEqual(accumulator.feed("x", 3.2), 0)
        self.assertEqual(accumulator.feed(8, None), 0)

    def test_reset_drops_the_carry(self):
        accumulator = ScrollAccumulator()
        accumulator.feed(1, 0.9)
        accumulator.reset()
        self.assertEqual(accumulator.residue, 0.0)


if __name__ == "__main__":
    unittest.main()
