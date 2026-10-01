import unittest

from ui.locale_manager import _TRANSLATIONS


class LocaleManagerTranslationTests(unittest.TestCase):
    def test_key_capture_error_messages_exist_in_all_locales(self):
        required = {
            "key_capture.error.unsupported_key",
            "key_capture.error.unknown_key",
            "key_capture.error.duplicate_key",
            "key_capture.error.multiple_main_keys",
            "key_capture.error.missing_main_key",
            "key_capture.error.empty_segment",
            "key_capture.error.unsupported",
        }

        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertTrue(required.issubset(strings))
                for key in required:
                    self.assertTrue(strings[key].strip())

    def test_key_capture_recorder_strings_exist_in_all_locales(self):
        required = {
            "key_capture.placeholder_recording",
            "key_capture.record_hint",
            "key_capture.type_hint",
            "key_capture.mode_type",
            "key_capture.mode_record",
        }

        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertTrue(required.issubset(strings))
                for key in required:
                    self.assertTrue(strings[key].strip())

    def test_key_capture_help_text_covers_the_supported_function_keys(self):
        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertIn("f24", strings["key_capture.valid_keys"])

    def test_update_install_messages_exist_in_all_locales(self):
        required = {
            "scroll.update_idle",
            "scroll.update_available",
            "scroll.update_checking",
            "scroll.update_downloading",
            "scroll.update_verifying",
            "scroll.update_ready",
            "scroll.update_installing",
            "scroll.update_installed",
            "scroll.update_installed_version",
            "scroll.update_cancelled",
            "scroll.update_manual",
            "scroll.update_manual_windows",
            "scroll.update_manual_macos",
            "scroll.update_manual_linux",
            "scroll.update_no_asset",
            "scroll.update_error",
            "scroll.update_error_check_first",
            "scroll.update_error_network_error",
            "scroll.update_error_metadata_missing",
            "scroll.update_error_metadata_invalid",
            "scroll.update_error_permission_denied",
            "scroll.update_error_file_error",
            "scroll.update_error_install_failed",
            "scroll.update_error_sha256_mismatch",
            "scroll.update_error_size_mismatch",
            "scroll.update_error_expired_metadata",
            "scroll.update_error_older_build",
            "scroll.update_check",
            "scroll.update_download",
            "scroll.update_cancel",
            "scroll.update_verify",
            "scroll.update_install",
            "scroll.update_open_release",
        }

        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertTrue(required.issubset(strings))
                for key in required:
                    self.assertTrue(strings[key].strip())


class AccessibilityLocaleTests(unittest.TestCase):
    """The QML accessibility labels added in this batch reference these
    keys. Missing them in a non-English locale silently regresses to a
    KeyError-as-empty-string in the QML lookup ``s[...]``, which leaves
    screen readers reading nothing for an interactive control.
    """

    REQUIRED_KEYS = frozenset({
        "dialog.close",
        "scroll.ignore_trackpad",
        "scroll.ignore_trackpad_desc",
        "scroll.smart_shift",
    })
    ENGLISH_VALUES = frozenset({
        "Close",
        "Ignore trackpad",
        "Only respond to mouse events, not trackpad or Magic Mouse",
    })

    def test_required_accessibility_keys_present_in_all_locales(self):
        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                missing = self.REQUIRED_KEYS - strings.keys()
                self.assertFalse(missing, f"{locale} missing keys: {missing}")
                for key in self.REQUIRED_KEYS:
                    self.assertTrue(
                        strings[key].strip(),
                        f"{locale}.{key} is blank",
                    )

    def test_chinese_locales_do_not_passthrough_english(self):
        """Trackpad strings used to ship English text in the zh_CN and
        zh_TW maps. Pin that they are now actually localized."""
        for locale in ("zh_CN", "zh_TW"):
            with self.subTest(locale=locale):
                for key in (
                    "scroll.ignore_trackpad",
                    "scroll.ignore_trackpad_desc",
                ):
                    self.assertNotIn(
                        _TRANSLATIONS[locale][key],
                        self.ENGLISH_VALUES,
                        f"{locale}.{key} still ships English",
                    )
                self.assertNotEqual(
                    _TRANSLATIONS[locale]["scroll.smart_shift"],
                    "SmartShift",
                    f"{locale}.scroll.smart_shift still ships English",
                )


# ──────────────────────────────────────────────────────────────────────────────
# Key-set parity
# ──────────────────────────────────────────────────────────────────────────────


class LocaleKeyParityTests(unittest.TestCase):
    def test_every_locale_carries_the_same_keys(self):
        # Parity holds today but nothing enforced it, so a page's worth of
        # strings could be added to English alone and ship green.
        english = set(_TRANSLATIONS["en"])
        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertEqual(set(strings) - english, set(),
                                 f"{locale} has keys English does not")
                self.assertEqual(english - set(strings), set(),
                                 f"{locale} is missing keys English has")

    def test_no_locale_ships_an_empty_string(self):
        for locale, strings in _TRANSLATIONS.items():
            for key, value in strings.items():
                with self.subTest(locale=locale, key=key):
                    self.assertTrue(value.strip(), f"{locale}.{key} is blank")


class ScrollPageStringTests(unittest.TestCase):
    REQUIRED = (
        "nav.scroll",
        "general.title",
        "general.subtitle",
        "scroll.title",
        "scroll.subtitle",
        "scroll.physical_v",
        "scroll.physical_h",
        "scroll.modified_v",
        "scroll.duration",
        "scroll.brake_point",
        "scroll.scroll_speed",
        "scroll.acceleration",
        "scroll.smoothness",
        "scroll.hscroll_speed",
        "scroll.smooth_scroll",
        "scroll.mod_shift_hscroll",
        "scroll.mod_ctrl_zoom",
        "scroll.mod_cmd_fast",
        "scroll.mod_super_fast",
        "scroll.mod_invert_hscroll",
        "scroll.mod_invert_zoom",
        "scroll.mod_gain",
        "scroll.graph_frames",
        "scroll.graph_speed",
        "scroll.graph_distance",
    )

    HELP_KEYS = (
        "scroll.smooth_scroll_help",
        "scroll.brake_point_help",
        "scroll.acceleration_help",
        "scroll.smoothness_help",
        "scroll.mod_gain_help",
    )

    def test_every_scroll_page_string_exists_in_every_locale(self):
        for locale, strings in _TRANSLATIONS.items():
            for key in self.REQUIRED + self.HELP_KEYS:
                with self.subTest(locale=locale, key=key):
                    self.assertIn(key, strings)

    def test_the_removed_presets_key_is_gone_everywhere(self):
        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertNotIn("scroll.scroll_speed_presets", strings)

    def test_the_scroll_page_title_is_no_longer_the_general_one(self):
        self.assertNotEqual(_TRANSLATIONS["en"]["scroll.title"],
                            _TRANSLATIONS["en"]["general.title"])


if __name__ == "__main__":
    unittest.main()
