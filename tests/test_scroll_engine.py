"""Tests for core.scroll_engine — curve, superposition, acceleration, driver."""

import math
import unittest

from core.scroll_engine import (
    AXIS_H,
    AXIS_V,
    H_DURATION_FRAMES,
    MAX_CATCHUP_FRAMES,
    MAX_CONSECUTIVE_ERRORS,
    MOD_ALT,
    MOD_CMD,
    MOD_CTRL,
    MOD_FAST,
    MOD_HSCROLL,
    MOD_NONE,
    MOD_PASSTHROUGH,
    MOD_SHIFT,
    MOD_ZOOM,
    RING_SIZE,
    ScrollConfig,
    ScrollCurve,
    ScrollDriver,
    ScrollEngine,
    SubPixelAccumulator,
    TickOutcome,
    _smooth_series,
    cumulative_profile,
    curve_samples,
    frame_profile,
    frame_weight,
    max_acceleration_gain,
    resolve_mod_mode,
    total_distance,
    total_distance_continuous,
)


def _config(**kwargs):
    curve = ScrollCurve(
        kwargs.pop("duration", 12),
        kwargs.pop("brake_point", 4),
        kwargs.pop("speed", 10),
    )
    kwargs.setdefault("enabled", True)
    kwargs.setdefault("acceleration", 0)
    return ScrollConfig(v=curve, **kwargs)


def _engine(**kwargs):
    return ScrollEngine(_config(**kwargs))


def _drain(engine, limit=1000):
    frames = []
    for _ in range(limit):
        frame = engine.next_frame()
        if frame is None:
            break
        frames.append(frame)
    return frames


def _drained_totals(engine, limit=1000):
    frames = _drain(engine, limit)
    return sum(f[0] for f in frames), sum(f[1] for f in frames)


def _feed_detents(engine, count, gap, t0=0.0, magnitude=1.0, axis=AXIS_V,
                  direction=1, modifiers=frozenset()):
    now = t0
    for _ in range(count):
        engine.push_tick(axis, direction, magnitude, now=now,
                         modifiers=modifiers)
        now += gap
    return now


def _feed_hires_detents(engine, count, gap, messages=15, step=0.001, t0=0.0):
    # One detent arrives as ~15 messages a millisecond apart, exactly as a
    # hi-res wheel reports it. The last message of each detent is what crosses
    # the whole-tick boundary, so detents stay `gap` apart.
    now = t0
    for _ in range(count):
        for index in range(messages):
            engine.push_tick(AXIS_V, 1, 1.0 / messages,
                             now=now + index * step)
        now += gap
    return now


# ──────────────────────────────────────────────────────────────────────────────
# Curve
# ──────────────────────────────────────────────────────────────────────────────


class CurveTests(unittest.TestCase):
    def test_default_profile_matches_the_reference_stroke(self):
        profile = frame_profile(12, 4, 10)
        self.assertEqual(len(profile), 12)
        self.assertEqual(profile[:5], [5.0] * 5)
        self.assertAlmostEqual(profile[-1], 0.625)

    def test_weight_is_one_at_the_brake_frame_itself(self):
        # f == B is the last frame of the plateau, not the first of the ramp:
        # (D - B) / (D - B) is 1.0, so the curve has no step at the join.
        self.assertEqual(frame_weight(4, 12, 4), 1.0)
        self.assertLess(frame_weight(5, 12, 4), 1.0)

    def test_weight_is_zero_at_and_past_the_end(self):
        self.assertEqual(frame_weight(12, 12, 4), 0.0)
        self.assertEqual(frame_weight(50, 12, 4), 0.0)

    def test_brake_at_or_past_duration_does_not_divide_by_zero(self):
        # Reachable from the UI by dragging duration down to 2 with the brake
        # already at 2 or higher.
        for brake in (2, 5, 12):
            profile = frame_profile(2, brake, 10)
            self.assertEqual(profile, [5.0, 5.0])
            self.assertTrue(all(math.isfinite(v) for v in profile))

    def test_discrete_total_is_what_ships_not_the_integral(self):
        self.assertAlmostEqual(total_distance(12, 4, 10), 42.5)
        self.assertAlmostEqual(total_distance_continuous(12, 4, 10), 40.0)

    def test_cumulative_profile_is_monotonic_and_ends_at_the_total(self):
        cumulative = cumulative_profile(12, 4, 10)
        self.assertEqual(cumulative, sorted(cumulative))
        self.assertAlmostEqual(cumulative[-1], total_distance(12, 4, 10))

    def test_out_of_range_inputs_are_clamped_not_rejected(self):
        self.assertEqual(len(frame_profile(9999, 4, 10)), 60)
        self.assertEqual(len(frame_profile(-5, 4, 10)), 2)
        self.assertEqual(frame_profile(12, 4, 9999)[0], 25.0)

    def test_curve_samples_run_one_frame_past_the_stroke(self):
        samples = curve_samples(12, 4, 10, 7, 0)
        self.assertEqual(len(samples), 13)
        self.assertEqual(samples[-1]["speed"], 0.0)
        totals = [s["total"] for s in samples]
        self.assertEqual(totals, sorted(totals))
        self.assertAlmostEqual(totals[-1], 42.5)

    def test_curve_samples_boosted_series_is_the_acceleration_ceiling(self):
        samples = curve_samples(12, 4, 10, 60, 0)
        self.assertAlmostEqual(max_acceleration_gain(60), 4.0)
        self.assertAlmostEqual(samples[0]["boosted"], samples[0]["speed"] * 4.0)

    def test_curve_samples_with_no_acceleration_do_not_boost(self):
        samples = curve_samples(12, 4, 10, 0, 0)
        for sample in samples:
            self.assertEqual(sample["boosted"], sample["speed"])

    def test_curve_samples_include_the_smoothing_tail(self):
        smoothed = curve_samples(12, 4, 10, 0, 5)
        self.assertGreater(len(smoothed), 13)
        self.assertGreater(smoothed[-1]["total"], 41.0)
        self.assertLessEqual(smoothed[-1]["total"], 42.5 + 1e-9)

    def test_degenerate_inputs_stay_finite(self):
        for sample in curve_samples(4, 4, 1, 0, 0):
            self.assertTrue(math.isfinite(sample["speed"]))
            self.assertTrue(math.isfinite(sample["total"]))


# ──────────────────────────────────────────────────────────────────────────────
# Superposition
# ──────────────────────────────────────────────────────────────────────────────


class SuperpositionTests(unittest.TestCase):
    def test_one_tick_delivers_its_whole_distance(self):
        engine = _engine()
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
        dy, dx = _drained_totals(engine)
        self.assertEqual(dy, 42)
        self.assertEqual(dx, 0)

    def test_repeated_ticks_do_not_drift(self):
        # The sub-pixel carry survives across strokes, so ten strokes of 42.5
        # must deliver 425 whole pixels, not ten truncations of 42.
        engine = _engine()
        total = 0
        for _ in range(10):
            engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
            total += _drained_totals(engine)[0]
        self.assertEqual(total, 425)

    def test_a_tick_added_mid_flight_superposes(self):
        engine = _engine()
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
        for _ in range(3):
            engine.next_frame()
        engine.push_tick(AXIS_V, 1, 1.0, now=0.05)
        engine.push_tick(AXIS_V, 1, 1.0, now=0.10)
        engine.push_tick(AXIS_V, 1, 1.0, now=0.15)

        engine2 = _engine()
        for _ in range(4):
            engine2.push_tick(AXIS_V, 1, 1.0, now=0.0)
        self.assertEqual(_drained_totals(engine2)[0], 170)

    def test_reversal_cancels_the_remaining_distance(self):
        engine = _engine()
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
        engine.push_tick(AXIS_V, -1, 1.0, now=0.0)
        self.assertEqual(_drained_totals(engine)[0], 0)

    def test_reversal_mid_glide_does_not_queue_behind_the_first_stroke(self):
        engine = _engine()
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
        for _ in range(2):
            engine.next_frame()
        engine.push_tick(AXIS_V, -1, 1.0, now=0.05)
        rest = _drain(engine)
        # The tail is dominated by the reversal, so it goes negative rather
        # than finishing the forward stroke first.
        self.assertLess(sum(f[0] for f in rest), 0)

    def test_fractional_magnitude_scales_the_whole_stroke(self):
        engine = _engine()
        for _ in range(15):
            engine.push_tick(AXIS_V, 1, 1.0 / 15.0, now=0.0)
        self.assertEqual(_drained_totals(engine)[0], 42)

    def test_ring_cannot_wrap_onto_frames_still_in_flight(self):
        self.assertGreater(RING_SIZE, 2 * 60)

    def test_longest_stroke_stays_conserved(self):
        engine = _engine(duration=60, brake_point=1, speed=50)
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
        expected = total_distance(60, 1, 50)
        self.assertEqual(_drained_totals(engine)[0], int(expected))

    def test_a_flywheel_spin_is_bounded(self):
        engine = _engine()
        for index in range(4000):
            engine.push_tick(AXIS_V, 1, 1.0, now=index * 0.0003)
        frames = _drain(engine, limit=5000)
        self.assertLess(len(frames), 200)

    def test_disabled_config_swallows_nothing_and_schedules_nothing(self):
        engine = ScrollEngine(_config(enabled=False))
        outcome = engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
        self.assertFalse(outcome.swallow)
        self.assertTrue(engine.idle)

    def test_zero_and_non_finite_magnitudes_are_ignored(self):
        engine = _engine()
        for magnitude in (0.0, float("nan"), float("inf"), "x", None):
            engine.push_tick(AXIS_V, 1, magnitude, now=0.0)
        self.assertTrue(engine.idle)


# ──────────────────────────────────────────────────────────────────────────────
# Acceleration
# ──────────────────────────────────────────────────────────────────────────────


class AccelerationTests(unittest.TestCase):
    def test_zero_acceleration_is_an_exact_no_op(self):
        slow = _engine(acceleration=0)
        _feed_detents(slow, 6, gap=0.5)
        fast = _engine(acceleration=0)
        _feed_detents(fast, 6, gap=0.01)
        self.assertEqual(_drained_totals(slow)[0], _drained_totals(fast)[0])

    def test_fast_scrolling_travels_further_than_slow(self):
        slow = _engine(acceleration=60)
        _feed_detents(slow, 6, gap=0.5)
        fast = _engine(acceleration=60)
        _feed_detents(fast, 6, gap=0.01)
        self.assertGreater(_drained_totals(fast)[0], _drained_totals(slow)[0])

    def test_rate_saturates_at_one_and_floors_at_zero(self):
        fast = _engine(acceleration=60)
        _feed_detents(fast, 12, gap=0.005)
        self.assertAlmostEqual(fast._v.rate, 1.0, places=3)

        slow = _engine(acceleration=60)
        _feed_detents(slow, 12, gap=0.25)
        self.assertEqual(slow._v.rate, 0.0)

    def test_mid_speed_lands_between_the_extremes(self):
        engine = _engine(acceleration=60)
        _feed_detents(engine, 12, gap=0.1)
        self.assertGreater(engine._v.rate, 0.0)
        self.assertLess(engine._v.rate, 1.0)

    def test_a_long_gap_resets_the_rate(self):
        engine = _engine(acceleration=60)
        end = _feed_detents(engine, 8, gap=0.005)
        self.assertGreater(engine._v.rate, 0.5)
        engine.push_tick(AXIS_V, 1, 1.0, now=end + 1.0)
        self.assertEqual(engine._v.rate, 0.0)

    def test_default_acceleration_tops_out_at_1_35x(self):
        self.assertAlmostEqual(max_acceleration_gain(7), 1.35)

    def test_a_hires_burst_counts_as_one_whole_tick(self):
        # Fifteen messages a millisecond apart is one detent, not a 1000 Hz
        # scroll. Timed naively every detent would get maximum boost.
        hires = _engine(acceleration=60)
        _feed_hires_detents(hires, 8, gap=0.12)
        coarse = _engine(acceleration=60)
        _feed_detents(coarse, 8, gap=0.12)
        self.assertAlmostEqual(hires._v.rate, coarse._v.rate, places=9)

    def test_a_hires_burst_does_not_reach_the_ceiling_on_its_own(self):
        hires = _engine(acceleration=60)
        _feed_hires_detents(hires, 8, gap=0.12)
        self.assertLess(hires._v.rate, 0.99)

    def test_the_first_tick_of_a_gesture_is_never_boosted(self):
        engine = _engine(acceleration=60)
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
        self.assertEqual(engine._v.rate, 0.0)
        self.assertEqual(_drained_totals(engine)[0], 42)


# ──────────────────────────────────────────────────────────────────────────────
# Smoothing
# ──────────────────────────────────────────────────────────────────────────────


class SmoothingTests(unittest.TestCase):
    def test_smoothness_zero_is_bit_exact(self):
        raw = frame_profile(12, 4, 10)
        self.assertEqual(_smooth_series(raw, 0), raw)

    def test_every_smoothness_conserves_distance(self):
        raw = frame_profile(12, 4, 10) + [0.0] * 200
        for smoothness in range(6):
            smoothed = _smooth_series(raw, smoothness)
            self.assertAlmostEqual(sum(smoothed), sum(raw), places=6)

    def test_smoothing_never_overshoots_the_raw_peak(self):
        raw = frame_profile(12, 4, 10)
        for smoothness in range(6):
            smoothed = _smooth_series(raw, smoothness)
            self.assertLessEqual(max(smoothed), max(raw) + 1e-12)

    def test_smoothing_preserves_delivered_distance_through_the_engine(self):
        for smoothness in range(6):
            engine = _engine(smoothness=smoothness)
            engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
            self.assertEqual(_drained_totals(engine)[0], 42)

    def test_smoothing_lengthens_the_glide(self):
        sharp = _engine(smoothness=0)
        sharp.push_tick(AXIS_V, 1, 1.0, now=0.0)
        soft = _engine(smoothness=5)
        soft.push_tick(AXIS_V, 1, 1.0, now=0.0)
        self.assertGreater(len(_drain(soft)), len(_drain(sharp)))


# ──────────────────────────────────────────────────────────────────────────────
# Sub-pixel carry
# ──────────────────────────────────────────────────────────────────────────────


class SubPixelAccumulatorTests(unittest.TestCase):
    def test_fractions_accumulate_without_drift(self):
        accumulator = SubPixelAccumulator()
        total = sum(accumulator.take(0.1) for _ in range(1000))
        self.assertEqual(total, 100)

    def test_truncation_does_not_leak_a_unit_at_a_reversal(self):
        accumulator = SubPixelAccumulator()
        self.assertEqual(accumulator.take(0.6), 0)
        self.assertEqual(accumulator.take(-0.6), 0)
        self.assertAlmostEqual(accumulator.residue, 0.0)

    def test_negative_runs_accumulate_symmetrically(self):
        accumulator = SubPixelAccumulator()
        total = sum(accumulator.take(-0.1) for _ in range(1000))
        self.assertEqual(total, -100)

    def test_non_finite_input_clears_rather_than_poisons(self):
        accumulator = SubPixelAccumulator()
        accumulator.take(0.5)
        self.assertEqual(accumulator.take(float("nan")), 0)
        self.assertEqual(accumulator.residue, 0.0)

    def test_unparseable_input_is_ignored(self):
        accumulator = SubPixelAccumulator()
        accumulator.take(0.5)
        self.assertEqual(accumulator.take("x"), 0)
        self.assertAlmostEqual(accumulator.residue, 0.5)

    def test_reset_drops_the_carry(self):
        accumulator = SubPixelAccumulator()
        accumulator.take(0.9)
        accumulator.reset()
        self.assertEqual(accumulator.take(0.5), 0)


# ──────────────────────────────────────────────────────────────────────────────
# Idle and lifecycle
# ──────────────────────────────────────────────────────────────────────────────


class LifecycleTests(unittest.TestCase):
    def test_a_fresh_engine_is_idle_and_emits_nothing(self):
        engine = _engine()
        self.assertTrue(engine.idle)
        self.assertIsNone(engine.next_frame())

    def test_pushing_wakes_the_engine_and_draining_settles_it(self):
        engine = _engine()
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
        self.assertFalse(engine.idle)
        _drain(engine)
        self.assertTrue(engine.idle)

    def test_reset_drops_everything_in_flight(self):
        engine = _engine()
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
        engine.reset()
        self.assertTrue(engine.idle)
        self.assertIsNone(engine.next_frame())

    def test_flush_emits_the_carry_then_resets(self):
        engine = _engine()
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
        _drain(engine)
        dy, dx = engine.flush()
        self.assertEqual((dy, dx), (0, 0))
        self.assertTrue(engine.idle)

    def test_disabling_mid_glide_stops_the_glide(self):
        engine = _engine()
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
        engine.configure(_config(enabled=False))
        self.assertTrue(engine.idle)

    def test_reconfiguring_while_enabled_keeps_the_glide(self):
        engine = _engine()
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
        engine.configure(_config(speed=20))
        self.assertFalse(engine.idle)

    def test_a_corrupt_smoothing_state_cannot_spin_forever(self):
        engine = _engine(smoothness=5)
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
        engine._v._ema = float("nan")
        self.assertLess(len(_drain(engine, limit=500)), 500)


# ──────────────────────────────────────────────────────────────────────────────
# Horizontal axis
# ──────────────────────────────────────────────────────────────────────────────


class HorizontalAxisTests(unittest.TestCase):
    def test_horizontal_uses_the_fixed_curve(self):
        engine = _engine(h_speed=10)
        engine.push_tick(AXIS_H, 1, 1.0, now=0.0)
        expected = total_distance(H_DURATION_FRAMES, 3, 10)
        self.assertEqual(_drained_totals(engine)[1], int(expected))

    def test_horizontal_ignores_the_acceleration_slider(self):
        slow = _engine(acceleration=60, h_speed=10)
        _feed_detents(slow, 6, gap=0.5, axis=AXIS_H)
        fast = _engine(acceleration=60, h_speed=10)
        _feed_detents(fast, 6, gap=0.005, axis=AXIS_H)
        self.assertEqual(_drained_totals(slow)[1], _drained_totals(fast)[1])

    def test_horizontal_speed_slider_scales_the_stroke(self):
        slow = _engine(h_speed=1)
        slow.push_tick(AXIS_H, 1, 1.0, now=0.0)
        fast = _engine(h_speed=50)
        fast.push_tick(AXIS_H, 1, 1.0, now=0.0)
        self.assertGreater(_drained_totals(fast)[1], _drained_totals(slow)[1])

    def test_horizontal_invert_flips_the_axis(self):
        engine = _engine(h_speed=10, invert_h=True)
        engine.push_tick(AXIS_H, 1, 1.0, now=0.0)
        self.assertLess(_drained_totals(engine)[1], 0)

    def test_vertical_invert_does_not_touch_horizontal(self):
        engine = _engine(h_speed=10, invert_v=True)
        engine.push_tick(AXIS_H, 1, 1.0, now=0.0)
        self.assertGreater(_drained_totals(engine)[1], 0)

    def test_vertical_invert_flips_the_vertical_axis(self):
        engine = _engine(invert_v=True)
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
        self.assertEqual(_drained_totals(engine)[0], -42)


# ──────────────────────────────────────────────────────────────────────────────
# Modifier routing
# ──────────────────────────────────────────────────────────────────────────────


class ModifierRoutingTests(unittest.TestCase):
    def test_no_modifier_is_a_plain_vertical_scroll(self):
        self.assertEqual(resolve_mod_mode(frozenset(), _config()), MOD_NONE)

    def test_each_modifier_routes_when_enabled(self):
        config = _config(
            mod_shift_hscroll=True,
            mod_ctrl_zoom=True,
            mod_cmd_fast=True,
        )
        self.assertEqual(resolve_mod_mode({MOD_SHIFT}, config), MOD_HSCROLL)
        self.assertEqual(resolve_mod_mode({MOD_CTRL}, config), MOD_ZOOM)
        self.assertEqual(resolve_mod_mode({MOD_CMD}, config), MOD_FAST)

    def test_a_disabled_modifier_falls_through_to_plain_scroll(self):
        config = _config(
            mod_shift_hscroll=False,
            mod_ctrl_zoom=False,
            mod_cmd_fast=False,
        )
        for mod in (MOD_SHIFT, MOD_CTRL, MOD_CMD):
            self.assertEqual(resolve_mod_mode({mod}, config), MOD_NONE)

    def test_two_known_modifiers_always_pass_through(self):
        config = _config(
            mod_shift_hscroll=True,
            mod_ctrl_zoom=False,
            mod_cmd_fast=True,
        )
        self.assertEqual(resolve_mod_mode({MOD_CTRL, MOD_SHIFT}, config),
                         MOD_PASSTHROUGH)
        self.assertEqual(resolve_mod_mode({MOD_SHIFT, MOD_CMD}, config),
                         MOD_PASSTHROUGH)
        self.assertEqual(resolve_mod_mode({MOD_CTRL, MOD_SHIFT, MOD_CMD}, config),
                         MOD_PASSTHROUGH)

    def test_alt_is_passed_through_untouched(self):
        # Alt+wheel is Photoshop's zoom. Treating Alt as "no modifier" would let
        # smooth scroll swallow the event and replay it as a plain glide.
        config = _config(mod_shift_hscroll=True)
        self.assertEqual(resolve_mod_mode({MOD_ALT}, config), MOD_PASSTHROUGH)
        self.assertEqual(resolve_mod_mode({MOD_SHIFT, MOD_ALT}, config),
                         MOD_PASSTHROUGH)

    def test_an_alt_tick_is_neither_swallowed_nor_animated(self):
        engine = _engine()
        outcome = engine.push_tick(AXIS_V, 1, 1.0, now=0.0,
                                   modifiers={MOD_ALT})
        self.assertFalse(outcome.swallow)
        self.assertEqual(outcome.passthrough_repeats, 0)
        self.assertTrue(engine.idle)

    def test_any_unhandled_modifier_passes_through(self):
        self.assertEqual(resolve_mod_mode({"fn"}, _config()), MOD_PASSTHROUGH)

    def test_the_full_truth_table_is_covered(self):
        config = _config(
            mod_shift_hscroll=True,
            mod_ctrl_zoom=True,
            mod_cmd_fast=True,
        )
        expected = {
            frozenset(): MOD_NONE,
            frozenset({MOD_SHIFT}): MOD_HSCROLL,
            frozenset({MOD_CTRL}): MOD_ZOOM,
            frozenset({MOD_CMD}): MOD_FAST,
            frozenset({MOD_SHIFT, MOD_CTRL}): MOD_PASSTHROUGH,
            frozenset({MOD_SHIFT, MOD_CMD}): MOD_PASSTHROUGH,
            frozenset({MOD_CTRL, MOD_CMD}): MOD_PASSTHROUGH,
            frozenset({MOD_SHIFT, MOD_CTRL, MOD_CMD}): MOD_PASSTHROUGH,
        }
        for held, mode in expected.items():
            self.assertEqual(resolve_mod_mode(held, config), mode, held)

    def test_shift_routes_a_vertical_tick_onto_the_horizontal_axis(self):
        engine = _engine(mod_shift_hscroll=True, h_speed=10)
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0, modifiers={MOD_SHIFT})
        dy, dx = _drained_totals(engine)
        self.assertEqual(dy, 0)
        self.assertGreater(dx, 0)

    def test_shift_hscroll_has_its_own_invert(self):
        engine = _engine(mod_shift_hscroll=True, h_speed=10,
                         invert_mod_h=True, invert_h=False)
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0, modifiers={MOD_SHIFT})
        self.assertLess(_drained_totals(engine)[1], 0)

    def test_cmd_fast_multiplies_the_stroke_by_the_gain(self):
        plain = _engine(mod_cmd_fast=True, mod_gain=4.0)
        plain.push_tick(AXIS_V, 1, 1.0, now=0.0)
        fast = _engine(mod_cmd_fast=True, mod_gain=4.0)
        fast.push_tick(AXIS_V, 1, 1.0, now=0.0, modifiers={MOD_CMD})
        self.assertEqual(_drained_totals(fast)[0],
                         4 * _drained_totals(plain)[0] + 2)

    def test_a_passthrough_tick_is_not_swallowed_and_schedules_nothing(self):
        engine = _engine(mod_shift_hscroll=True, mod_ctrl_zoom=True)
        outcome = engine.push_tick(AXIS_V, 1, 1.0, now=0.0,
                                   modifiers={MOD_SHIFT, MOD_CTRL})
        self.assertEqual(outcome, TickOutcome())
        self.assertTrue(engine.idle)


# ──────────────────────────────────────────────────────────────────────────────
# Ctrl zoom quantization
# ──────────────────────────────────────────────────────────────────────────────


class ZoomQuantizationTests(unittest.TestCase):
    def _repeats(self, engine, count, modifiers=None):
        modifiers = modifiers or {MOD_CTRL}
        out = []
        for index in range(count):
            outcome = engine.push_tick(AXIS_V, 1, 1.0, now=index * 0.05,
                                       modifiers=modifiers)
            steps = outcome.passthrough_repeats
            if not steps and not outcome.swallow:
                steps = 1
            out.append(steps)
        return out

    def test_fractional_gain_is_carried_across_detents(self):
        engine = _engine(mod_ctrl_zoom=True, mod_gain=3.2)
        self.assertEqual(self._repeats(engine, 5), [3, 3, 3, 3, 4])

    def test_zoom_never_animates(self):
        engine = _engine(mod_ctrl_zoom=True, mod_gain=3.2)
        engine.push_tick(AXIS_V, 1, 1.0, now=0.0, modifiers={MOD_CTRL})
        self.assertTrue(engine.idle)

    def test_a_hires_burst_zooms_once_per_detent(self):
        engine = _engine(mod_ctrl_zoom=True, mod_gain=1.0)
        fired = 0
        for index in range(15):
            outcome = engine.push_tick(AXIS_V, 1, 1.0 / 15.0,
                                       now=index * 0.001,
                                       modifiers={MOD_CTRL})
            if outcome.passthrough_repeats or not outcome.swallow:
                fired += 1
        self.assertEqual(fired, 1)

    def test_sub_detent_fragments_are_swallowed_not_leaked(self):
        engine = _engine(mod_ctrl_zoom=True, mod_gain=3.2)
        outcome = engine.push_tick(AXIS_V, 1, 0.1, now=0.0,
                                   modifiers={MOD_CTRL})
        self.assertTrue(outcome.swallow)
        self.assertEqual(outcome.passthrough_repeats, 0)

    def test_a_unit_gain_lets_the_original_event_through(self):
        engine = _engine(mod_ctrl_zoom=True, mod_gain=1.0)
        outcome = engine.push_tick(AXIS_V, 1, 1.0, now=0.0,
                                   modifiers={MOD_CTRL})
        self.assertEqual(outcome, TickOutcome())

    def test_zoom_inversion_blocks_and_reposts_in_the_other_direction(self):
        engine = _engine(mod_ctrl_zoom=True, mod_gain=1.0, invert_zoom=True)
        outcome = engine.push_tick(AXIS_V, 1, 1.0, now=0.0,
                                   modifiers={MOD_CTRL})
        self.assertTrue(outcome.swallow)
        self.assertEqual(outcome.passthrough_repeats, 1)
        self.assertEqual(outcome.passthrough_direction, -1)

    def test_a_small_gain_still_zooms(self):
        engine = _engine(mod_ctrl_zoom=True, mod_gain=0.1)
        self.assertTrue(all(n >= 1 for n in self._repeats(engine, 10)))

    def test_repeats_are_capped(self):
        engine = _engine(mod_ctrl_zoom=True, mod_gain=10.0)
        for repeats in self._repeats(engine, 5):
            self.assertLessEqual(repeats, 20)


# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────


class ScrollConfigTests(unittest.TestCase):
    def test_from_settings_reads_every_key(self):
        config = ScrollConfig.from_settings({
            "vscroll_smooth": True,
            "vscroll_duration": 20,
            "vscroll_brake_point": 6,
            "vscroll_speed": 30,
            "vscroll_acceleration": 12,
            "vscroll_smoothness": 3,
            "hscroll_speed": 9,
            "invert_vscroll": True,
            "invert_hscroll": True,
            "mod_scroll_shift_hscroll": False,
            "mod_scroll_ctrl_zoom": True,
            "mod_scroll_cmd_fast": True,
            "mod_scroll_invert_hscroll": True,
            "mod_scroll_invert_zoom": True,
            "mod_scroll_gain": 4.5,
        })
        self.assertTrue(config.enabled)
        self.assertEqual(config.v, ScrollCurve(20, 6, 30))
        self.assertEqual(config.acceleration, 12)
        self.assertEqual(config.smoothness, 3)
        self.assertEqual(config.h_speed, 9)
        self.assertTrue(config.invert_v)
        self.assertTrue(config.invert_h)
        self.assertFalse(config.mod_shift_hscroll)
        self.assertTrue(config.mod_ctrl_zoom)
        self.assertTrue(config.mod_cmd_fast)
        self.assertTrue(config.invert_mod_h)
        self.assertTrue(config.invert_zoom)
        self.assertAlmostEqual(config.mod_gain, 4.5)

    def test_native_invert_suppresses_software_inversion(self):
        settings = {
            "invert_vscroll": True,
            "invert_hscroll": True,
        }
        self.assertTrue(ScrollConfig.from_settings(settings).invert_v)
        suppressed = ScrollConfig.from_settings(settings,
                                                native_invert_active=True)
        self.assertFalse(suppressed.invert_v)
        self.assertFalse(suppressed.invert_h)

    def test_from_settings_survives_an_empty_dict(self):
        config = ScrollConfig.from_settings({})
        self.assertFalse(config.enabled)
        self.assertEqual(config.v, ScrollCurve(12, 4, 10))

    def test_values_are_clamped_to_their_slider_ranges(self):
        config = ScrollConfig.from_settings({
            "vscroll_duration": 9999,
            "vscroll_speed": -3,
            "vscroll_acceleration": 900,
            "vscroll_smoothness": 40,
            "hscroll_speed": 0,
            "mod_scroll_gain": 99.0,
        })
        self.assertEqual(config.v.duration, 60)
        self.assertEqual(config.v.speed, 1)
        self.assertEqual(config.acceleration, 60)
        self.assertEqual(config.smoothness, 5)
        self.assertEqual(config.h_speed, 1)
        self.assertEqual(config.mod_gain, 10.0)

    def test_garbage_values_fall_back_to_defaults(self):
        config = ScrollConfig.from_settings({
            "vscroll_duration": "twelve",
            "mod_scroll_gain": float("nan"),
        })
        self.assertEqual(config.v.duration, 12)
        self.assertAlmostEqual(config.mod_gain, 3.2)

    def test_brake_point_can_never_exceed_duration(self):
        self.assertEqual(ScrollCurve(2, 12, 10).brake_point, 2)

    def test_the_horizontal_curve_is_fixed(self):
        config = _config(h_speed=7)
        self.assertEqual(config.h_curve, ScrollCurve(H_DURATION_FRAMES, 3, 7))

    def test_config_and_curve_are_immutable(self):
        with self.assertRaises(AttributeError):
            _config().enabled = False
        with self.assertRaises(AttributeError):
            ScrollCurve().speed = 4


# ──────────────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────────────


class _CountingWrapper:
    def __init__(self):
        self.entered = 0

    def __call__(self):
        return self

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, *exc):
        return False


class _StubEngine:
    def __init__(self, frames=None):
        self.config = ScrollConfig()
        self.frames = list(frames) if frames is not None else None
        self.calls = 0
        self.reset_calls = 0

    def next_frame(self, now=None):
        self.calls += 1
        if self.frames is None:
            return (1, 0)
        return self.frames.pop(0) if self.frames else None

    @property
    def idle(self):
        return self.frames is not None and not self.frames

    def flush(self):
        return (7, 0)

    def reset(self):
        self.reset_calls += 1


def _driver(engine, emit, wrapper=None, interval=1.0 / 60.0):
    return ScrollDriver(engine, emit, frame_interval_s=interval,
                        frame_wrapper=wrapper or _CountingWrapper())


class ScrollDriverTests(unittest.TestCase):
    def test_one_wake_up_on_time_emits_one_frame(self):
        engine = _StubEngine()
        emitted = []
        driver = _driver(engine, lambda dy, dx: emitted.append((dy, dx)))
        self.assertTrue(driver._run_once(0.0))
        self.assertEqual(emitted, [(1, 0)])

    def test_a_late_wake_up_catches_up(self):
        engine = _StubEngine()
        emitted = []
        driver = _driver(engine, lambda dy, dx: emitted.append((dy, dx)))
        driver._run_once(0.0)
        emitted.clear()
        driver._run_once(2.5 / 60.0)
        self.assertEqual(len(emitted), 2)

    def test_catch_up_is_bounded_and_resyncs(self):
        engine = _StubEngine()
        emitted = []
        driver = _driver(engine, lambda dy, dx: emitted.append((dy, dx)))
        driver._run_once(0.0)
        emitted.clear()
        driver._run_once(5.0)
        self.assertEqual(len(emitted), 1)
        self.assertAlmostEqual(driver._next_frame_at, 5.0 + 1.0 / 60.0)

    def test_never_replays_more_than_the_catch_up_bound(self):
        engine = _StubEngine()
        emitted = []
        driver = _driver(engine, lambda dy, dx: emitted.append((dy, dx)))
        driver._run_once(0.0)
        emitted.clear()
        driver._run_once(MAX_CATCHUP_FRAMES / 60.0)
        self.assertLessEqual(len(emitted), MAX_CATCHUP_FRAMES)

    def test_the_frame_wrapper_is_entered_once_per_frame(self):
        engine = _StubEngine()
        wrapper = _CountingWrapper()
        driver = _driver(engine, lambda dy, dx: None, wrapper=wrapper)
        driver._run_once(0.0)
        driver._run_once(2.5 / 60.0)
        self.assertEqual(wrapper.entered, 3)

    def test_a_zero_frame_is_not_emitted(self):
        engine = _StubEngine(frames=[(0, 0), (1, 0)])
        emitted = []
        driver = _driver(engine, lambda dy, dx: emitted.append((dy, dx)))
        driver._run_once(0.0)
        driver._run_once(1.0 / 60.0)
        self.assertEqual(emitted, [(1, 0)])

    def test_an_idle_engine_clears_the_schedule(self):
        engine = _StubEngine(frames=[])
        driver = _driver(engine, lambda dy, dx: None)
        self.assertTrue(driver._run_once(0.0))
        self.assertIsNone(driver._next_frame_at)

    def test_isolated_emit_errors_do_not_stop_the_loop(self):
        engine = _StubEngine()

        def _boom(dy, dx):
            raise RuntimeError("tap gone")

        driver = _driver(engine, _boom)
        for _ in range(MAX_CONSECUTIVE_ERRORS - 1):
            self.assertTrue(driver._run_once(driver._next_frame_at or 0.0))

    def test_the_loop_gives_up_after_ten_consecutive_errors(self):
        engine = _StubEngine()

        def _boom(dy, dx):
            raise RuntimeError("tap gone")

        driver = _driver(engine, _boom)
        results = [driver._run_once(index / 60.0)
                   for index in range(MAX_CONSECUTIVE_ERRORS + 2)]
        self.assertIn(False, results)

    def test_a_successful_frame_clears_the_error_streak(self):
        engine = _StubEngine()
        fail = [True]

        def _sometimes(dy, dx):
            if fail[0]:
                raise RuntimeError("transient")

        driver = _driver(engine, _sometimes)
        for index in range(MAX_CONSECUTIVE_ERRORS - 1):
            driver._run_once(index / 60.0)
        fail[0] = False
        driver._run_once(MAX_CONSECUTIVE_ERRORS / 60.0)
        self.assertEqual(driver._errors, 0)

    def test_stop_without_flush_resets_the_engine(self):
        engine = _StubEngine()
        emitted = []
        driver = _driver(engine, lambda dy, dx: emitted.append((dy, dx)))
        driver.stop()
        self.assertEqual(engine.reset_calls, 1)
        self.assertEqual(emitted, [])

    def test_stop_with_flush_emits_the_carry(self):
        engine = _StubEngine()
        emitted = []
        driver = _driver(engine, lambda dy, dx: emitted.append((dy, dx)))
        driver.stop(flush=True)
        self.assertEqual(emitted, [(7, 0)])

    def test_start_and_stop_are_idempotent(self):
        engine = ScrollEngine(_config())
        driver = ScrollDriver(engine, lambda dy, dx: None)
        driver.start()
        driver.start()
        self.assertTrue(driver.running)
        driver.stop()
        driver.stop()
        self.assertFalse(driver.running)

    def test_a_real_glide_runs_to_completion_on_the_thread(self):
        engine = ScrollEngine(_config())
        emitted = []
        driver = ScrollDriver(engine, lambda dy, dx: emitted.append((dy, dx)))
        driver.start()
        try:
            engine.push_tick(AXIS_V, 1, 1.0, now=0.0)
            driver.wake()
            deadline = 2.0
            step = 0.01
            waited = 0.0
            while waited < deadline and not engine.idle:
                import time as _time
                _time.sleep(step)
                waited += step
        finally:
            driver.stop()
        self.assertEqual(sum(dy for dy, _ in emitted), 42)


if __name__ == "__main__":
    unittest.main()
