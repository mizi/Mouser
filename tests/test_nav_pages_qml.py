"""Source guards for the sidebar-to-page index invariant.

navModel and the StackLayout are aligned by hand: the nth declared child is the
page the nth entry's `page:` number selects. Nothing at runtime checks that, so
a literal typed into one and not the other opens the wrong page silently.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
QML_DIR = ROOT / "ui" / "qml"
MAIN = (QML_DIR / "Main.qml").read_text(encoding="utf-8")

PAGE_CONSTANTS = (
    "pageMouse",
    "pageScroll",
    "pageHaptic",
    "pageRing",
    "pageGeneral",
)


class PageIndexConstantTests(unittest.TestCase):
    def test_every_page_has_a_named_constant(self):
        for name in PAGE_CONSTANTS:
            with self.subTest(page=name):
                self.assertIn(f"readonly property int {name}:", MAIN)

    def test_the_constants_are_consecutive_from_zero(self):
        values = []
        for name in PAGE_CONSTANTS:
            match = re.search(rf"readonly property int {name}: (\d+)", MAIN)
            self.assertIsNotNone(match, name)
            values.append(int(match.group(1)))
        self.assertEqual(values, list(range(len(PAGE_CONSTANTS))))

    def test_every_constant_selects_a_sidebar_entry(self):
        for name in PAGE_CONSTANTS:
            with self.subTest(page=name):
                self.assertIn(f"page: root.{name}", MAIN)

    def test_every_lazily_loaded_page_gates_on_its_own_constant(self):
        # MousePage is inlined as child 0 and always live, so it has no gate;
        # every Loader must name the constant its position implies.
        for name in PAGE_CONSTANTS[1:]:
            with self.subTest(page=name):
                self.assertIn(f"root.currentPage === root.{name}", MAIN)

    def test_no_bare_index_literals_remain(self):
        self.assertNotRegex(MAIN, r"page: \d")
        self.assertNotRegex(MAIN, r"currentPage === \d")


class StackChildTests(unittest.TestCase):
    def _stack_body(self):
        start = MAIN.index("StackLayout {")
        depth = 0
        for index in range(start, len(MAIN)):
            if MAIN[index] == "{":
                depth += 1
            elif MAIN[index] == "}":
                depth -= 1
                if depth == 0:
                    return MAIN[start:index + 1]
        self.fail("StackLayout never closes")

    def test_the_stack_declares_one_child_per_page(self):
        body = self._stack_body()
        children = body.count("Loader {") + body.count("MousePage {")
        self.assertEqual(children, len(PAGE_CONSTANTS))

    def test_every_page_source_exists(self):
        for source in re.findall(r'source: "([^"]+\.qml)"', MAIN):
            with self.subTest(source=source):
                self.assertTrue((QML_DIR / source).exists(), source)

    def test_the_scroll_and_general_pages_are_both_loaded(self):
        body = self._stack_body()
        self.assertIn('source: "ScrollPage.qml"', body)
        self.assertIn('source: "GeneralPage.qml"', body)

    def test_the_mouse_page_stays_inlined(self):
        # mousePageView.hasBlockingDialog is bound by id, so it cannot become a
        # Loader without that binding losing its target.
        self.assertIn("id: mousePageView", self._stack_body())

    def test_the_scroll_tab_sits_second_in_the_sidebar(self):
        nav = MAIN[MAIN.index("property var navModel"):MAIN.index("function openPage")]
        order = re.findall(r'tipKey: "([^"]+)"', nav)
        self.assertEqual(order[:2], ["nav.mouse_profiles", "nav.scroll"])
        self.assertEqual(order[-1], "nav.point_scroll")

    def test_the_scroll_tab_has_an_icon_on_disk(self):
        nav = MAIN[MAIN.index("property var navModel"):MAIN.index("function openPage")]
        for icon in re.findall(r'icon: "([^"]+)"', nav):
            with self.subTest(icon=icon):
                self.assertTrue(
                    (ROOT / "images" / "icons" / f"{icon}.svg").exists(), icon
                )


if __name__ == "__main__":
    unittest.main()
