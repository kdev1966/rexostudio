"""Transcription : profils par langue, detection de langue, nettoyage."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import config, transcribe  # noqa: E402


def installed(*names):
    return lambda name: ("/models/ggml-%s.bin" % name) if name in names else ""


class ProfileTest(unittest.TestCase):
    def test_arabic_uses_small_without_context(self):
        with mock.patch.object(config, "whisper_model_path", installed("base", "small")):
            model, profile = transcribe.choose_profile("ar")
        self.assertEqual(model, "small")
        self.assertTrue(profile["no_context"])

    def test_french_keeps_default_model(self):
        with mock.patch.object(config, "whisper_model_path", installed("base", "small")):
            model, profile = transcribe.choose_profile("fr")
        self.assertEqual(model, "base")
        self.assertFalse(profile["no_context"])

    def test_explicit_choice_wins(self):
        with mock.patch.object(config, "whisper_model_path", installed("base", "small")):
            self.assertEqual(transcribe.choose_profile("ar", "base")[0], "base")

    def test_missing_profile_model_falls_back(self):
        with mock.patch.object(config, "whisper_model_path", installed("base")):
            self.assertEqual(transcribe.choose_profile("ar")[0], "base")


class DetectLanguageTest(unittest.TestCase):
    def test_parses_whisper_output(self):
        out = ("whisper_model_load: n_langs = 99\n"
               "whisper_full_with_state: auto-detected language: ar (p = 0.980798)\n")
        with mock.patch.object(config, "whisper_bin", return_value="/bin/whisper-cli"), \
                mock.patch.object(config, "whisper_model_path", installed("base")), \
                mock.patch.object(transcribe.tools, "run_streaming", return_value=out) as run:
            self.assertEqual(transcribe.detect_language("/a.wav"), "ar")
        self.assertIn("-dl", run.call_args[0][0])

    def test_failure_returns_empty(self):
        with mock.patch.object(config, "whisper_bin", return_value="/bin/whisper-cli"), \
                mock.patch.object(config, "whisper_model_path", installed("base")), \
                mock.patch.object(transcribe.tools, "run_streaming",
                                  side_effect=transcribe.tools.CommandError("x", 1, "")):
            self.assertEqual(transcribe.detect_language("/a.wav"), "")


class CleanWordsTest(unittest.TestCase):
    def test_stretched_letters_and_quotes(self):
        words = transcribe.clean_words([
            {"start": 0, "end": 1, "text": ' "ههههههههههه"'},
            {"start": 1, "end": 2, "text": " 10000"},
            {"start": 2, "end": 3, "text": " Ouiiiiii"}])
        self.assertEqual([w["text"] for w in words], ["ههه", "10000", "Ouiii"])


if __name__ == "__main__":
    unittest.main()
