"""Source guards for the Scroll page and its two new components.

QML is not exercised by any runtime harness here, so the invariants that would
otherwise only show up as a misbehaving page are pinned as source checks.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
QML_DIR = ROOT / "ui" / "qml"


def _read(name):
    return (QML_DIR / name).read_text(encoding="utf-8")


SCROLL = _read("ScrollPage.qml")
GENERAL = _read("GeneralPage.qml")
GRAPH = _read("ScrollCurveGraph.qml")
HINT = _read("HelpHint.qml")
NEW_FILES = {
    "ScrollPage.qml": SCROLL,
    "ScrollCurveGraph.qml": GRAPH,
    "HelpHint.qml": HINT,
}


# ──────────────────────────────────────────────────────────────────────────────
# Moved, not copied
# ──────────────────────────────────────────────────────────────────────────────


class PageSplitTests(unittest.TestCase):
    MOVED = ("vscrollSwitch", "hscrollSwitch", "ignoreTrackpadSwitch",
             "smartShiftSlider", "scrollForceSlider")
    STAYED = ("dpiSlider", "checkUpdatesSwitch", "startAtLoginSwitch")

    def test_the_scroll_controls_are_on_the_scroll_page(self):
        for name in self.MOVED:
            with self.subTest(control=name):
                self.assertIn(name, SCROLL)

    def test_the_scroll_controls_left_the_general_page(self):
        # Copied rather than moved means two widgets writing one setting, and
        # only one of them ever redrawing.
        for name in self.MOVED:
            with self.subTest(control=name):
                self.assertNotIn(name, GENERAL)

    def test_the_app_preferences_stayed_on_the_general_page(self):
        for name in self.STAYED:
            with self.subTest(control=name):
                self.assertIn(name, GENERAL)
                self.assertNotIn(name, SCROLL)

    def test_pointer_speed_is_not_a_scroll_setting(self):
        self.assertIn("scroll.pointer_speed", GENERAL)
        self.assertNotIn("scroll.pointer_speed", SCROLL)

    def test_each_page_uses_its_own_header_strings(self):
        self.assertIn('s["scroll.title"]', SCROLL)
        self.assertIn('s["general.title"]', GENERAL)
        self.assertNotIn('s["scroll.title"]', GENERAL)

    def test_the_general_page_id_matches_its_filename(self):
        self.assertIn("id: generalPage", GENERAL)
        self.assertIn("id: scrollPage", SCROLL)


# ──────────────────────────────────────────────────────────────────────────────
# Debounce discipline
# ──────────────────────────────────────────────────────────────────────────────


class DebounceTests(unittest.TestCase):
    def test_every_slider_has_a_commit_timer(self):
        # save_config does an atomic write plus an fsync; running that on every
        # frame of a drag would stall the UI thread.
        self.assertEqual(SCROLL.count("WheelSafeSlider {"),
                         SCROLL.count("interval: 400"))

    def test_the_graph_redraws_on_its_own_faster_timer(self):
        self.assertIn("interval: 60", SCROLL)
        self.assertEqual(SCROLL.count("interval: 60"), 1)

    def test_a_debounce_timer_reads_its_own_slider(self):
        # A Timer is a sibling of the slider, so a bare `value` inside it
        # resolves to nothing and the commit silently writes undefined.
        for match in re.finditer(r"id: (\w+)Debounce\s+interval: 400\s+"
                                 r"onTriggered: ([^\n]+)", SCROLL):
            ident, commit = match.group(1), match.group(2)
            with self.subTest(timer=ident):
                self.assertIn(f"{ident}Slider.value", commit)

    def test_the_page_re_reads_the_sliders_when_the_backend_writes(self):
        # _applyScrollTuning can clamp the brake point the user never touched.
        self.assertIn("function onScrollSettingsChanged()", SCROLL)
        self.assertIn("syncTuningSliders", SCROLL)


# ──────────────────────────────────────────────────────────────────────────────
# Packaging
# ──────────────────────────────────────────────────────────────────────────────


class QmlImportTests(unittest.TestCase):
    BANNED = ("QtCharts", "QtQuick.Shapes")

    def test_no_new_file_pulls_in_an_unpackaged_module(self):
        # Both are absent from the PyInstaller spec's QtQuick keep-list, so
        # either one turns a working page into a blank one in a release build.
        for name, source in NEW_FILES.items():
            for module in self.BANNED:
                with self.subTest(file=name, module=module):
                    self.assertNotIn(f"import {module}", source)

    def test_the_graph_uses_canvas_from_qtquick_core(self):
        self.assertIn("Canvas {", GRAPH)
        self.assertIn("import QtQuick", GRAPH)


# ──────────────────────────────────────────────────────────────────────────────
# Graph
# ──────────────────────────────────────────────────────────────────────────────


class ScrollCurveGraphTests(unittest.TestCase):
    def test_the_curve_comes_from_the_backend(self):
        # A JavaScript copy would be a second implementation of the same
        # physics with nothing keeping the two equal.
        self.assertIn("backend.scrollCurveSamples(", SCROLL)
        self.assertNotIn("function frameWeight", GRAPH)
        self.assertNotIn("brake_point", GRAPH)

    def test_canvas_repaints_are_explicit(self):
        # Canvas does not rebind on a property change.
        for trigger in ("onSamplesChanged", "onThemeChanged", "onWidthChanged",
                        "onHeightChanged", "onBrakePointChanged"):
            with self.subTest(trigger=trigger):
                self.assertIn(f"{trigger}: plot.requestPaint()", GRAPH)

    def test_the_graph_repaints_on_theme_and_language_changes(self):
        self.assertIn("function onDarkModeChanged() { plot.requestPaint() }",
                      GRAPH)
        self.assertIn("function onLanguageChanged() { plot.requestPaint() }",
                      GRAPH)

    def test_the_axis_maxima_are_derived(self):
        # At speed 50 the peak is 25 px per frame; a fixed 0-5 axis would draw
        # the curve off the top of the box.
        self.assertIn("speedAxisMax", GRAPH)
        self.assertIn("Math.ceil", GRAPH)

    def test_the_graph_does_not_swallow_the_wheel(self):
        # A decoration that grabs the pointer would stop the page scrolling
        # whenever the cursor rested on it.
        self.assertNotIn("MouseArea {", GRAPH)
        self.assertNotIn("onWheel", GRAPH)


# ──────────────────────────────────────────────────────────────────────────────
# Help hints
# ──────────────────────────────────────────────────────────────────────────────


class HelpHintTests(unittest.TestCase):
    def test_the_hint_never_eats_a_wheel_event(self):
        # It sits on a scrolling page; swallowing the wheel would make the page
        # stick wherever the pointer happened to rest.
        self.assertNotIn("onWheel", HINT)
        self.assertIn("scrollGestureEnabled: false", HINT)

    def test_the_bubble_escapes_the_clipping_scroll_view(self):
        self.assertIn("parent: Overlay.overlay", HINT)
        self.assertIn("Popup {", HINT)

    def test_the_hint_is_reachable_from_the_keyboard(self):
        self.assertIn("Accessible.role: Accessible.Button", HINT)
        self.assertIn("Keys.onReturnPressed", HINT)
        self.assertIn("Keys.onSpacePressed", HINT)

    def test_hints_are_attached_to_the_controls_that_need_them(self):
        expected = {
            "scroll.smooth_scroll_help",
            "scroll.brake_point_help",
            "scroll.acceleration_help",
            "scroll.smoothness_help",
            "scroll.mod_gain_help",
        }
        used = set(re.findall(r'HelpHint \{\s+text: s\["([^"]+)"\]', SCROLL))
        self.assertEqual(used, expected)

    def test_a_hint_never_sits_inside_a_slider_row(self):
        # In the RowLayout it would steal width from the slider and put a hover
        # target directly on the drag path.
        for match in re.finditer(r"RowLayout \{[^}]*", SCROLL):
            self.assertNotIn("HelpHint", match.group(0))



# ──────────────────────────────────────────────────────────────────────────────
# Per-app Shift+wheel
# ──────────────────────────────────────────────────────────────────────────────


class PerAppShiftTests(unittest.TestCase):
    def test_the_rows_come_from_the_backend(self):
        self.assertIn("model: backend.profileShiftHScroll", SCROLL)

    def test_every_mode_the_backend_accepts_has_a_chip(self):
        for mode in ("inherit", "on", "off"):
            with self.subTest(mode=mode):
                self.assertIn(f'value: "{mode}"', SCROLL)

    def test_a_chip_writes_through_the_backend_slot(self):
        self.assertIn("backend.setProfileShiftHScroll(", SCROLL)

    def test_the_section_sits_under_the_shift_switch(self):
        self.assertLess(SCROLL.index("id: modShiftSwitch"),
                        SCROLL.index("model: backend.profileShiftHScroll"))
        self.assertLess(SCROLL.index("model: backend.profileShiftHScroll"),
                        SCROLL.index("id: modCtrlSwitch"))

    def test_there_is_an_empty_state(self):
        self.assertIn('s["scroll.mod_shift_per_app_empty"]', SCROLL)


if __name__ == "__main__":
    unittest.main()
