"""Unit tests for the Input Locker i18n (internationalization) subsystem."""
import pytest

from input_locker.core.i18n import (
    SUPPORTED_LANGUAGES,
    TRANSLATIONS,
    TranslationManager,
    get_current_locale,
    set_locale,
    t,
)


class TestI18nCatalog:
    """Validate completeness and consistency of translation catalogs."""

    def test_supported_languages_presence(self):
        expected = {"en", "es", "fr", "de", "ja", "zh", "hi"}
        assert expected.issubset(set(SUPPORTED_LANGUAGES.keys()))

    def test_all_supported_languages_have_catalogs(self):
        for lang_code in SUPPORTED_LANGUAGES:
            assert lang_code in TRANSLATIONS, f"Missing catalog for {lang_code}"
            assert len(TRANSLATIONS[lang_code]) > 20, f"Catalog for {lang_code} is too small"

    def test_english_keys_are_defined_in_all_catalogs(self):
        en_keys = set(TRANSLATIONS["en"].keys())
        for lang, catalog in TRANSLATIONS.items():
            if lang == "en":
                continue
            missing = en_keys - set(catalog.keys())
            # All primary UI keys should be translated
            assert not missing, f"Language {lang} is missing keys: {missing}"

    def test_translation_manager_singleton(self):
        mgr1 = TranslationManager.get_instance()
        mgr2 = TranslationManager.get_instance()
        assert mgr1 is mgr2

    def test_fallback_to_english_for_unknown_key(self):
        set_locale("es")
        # If a key doesn't exist anywhere, return the key itself
        assert t("non_existent_random_key_123") == "non_existent_random_key_123"

    def test_locale_switching(self):
        set_locale("es")
        assert get_current_locale() == "es"
        assert "Bloquear" in t("btn_lock_now")

        set_locale("fr")
        assert get_current_locale() == "fr"
        assert "Verrouiller" in t("btn_lock_now")

        set_locale("de")
        assert get_current_locale() == "de"
        assert "Sperren" in t("btn_lock_now")

        set_locale("ja")
        assert get_current_locale() == "ja"
        assert "ロック" in t("btn_lock_now")

        set_locale("zh")
        assert get_current_locale() == "zh"
        assert "锁定" in t("btn_lock_now")

        set_locale("hi")
        assert get_current_locale() == "hi"
        assert "स्क्रीन लॉक" in t("btn_lock_now")

        # Reset to English
        set_locale("en")
        assert get_current_locale() == "en"
        assert "Lock Screen Now" in t("btn_lock_now")

    def test_fallback_on_unsupported_locale(self):
        set_locale("xx_unsupported")
        assert get_current_locale() == "en"
        assert t("btn_lock_now") == "🔒 Lock Screen Now"

    def test_parameter_interpolation(self):
        set_locale("en")
        formatted = t("tut_step1_desc", hotkey="F11")
        assert "Press F11 at any time" in formatted

        set_locale("es")
        formatted_es = t("tut_step1_desc", hotkey="F11")
        assert "Presione F11" in formatted_es

    def test_safe_formatting_missing_kwargs(self):
        set_locale("en")
        # Should not crash if kwarg is missing; returns template string
        result = t("tut_step1_desc")
        assert "{hotkey}" in result

    def test_system_language_detection(self):
        detected = TranslationManager.detect_system_language()
        assert detected in SUPPORTED_LANGUAGES or detected == "en"
