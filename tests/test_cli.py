"""Mode terminal : meme regle de suggestions que l'interface."""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from montagia import cli  # noqa: E402

RESULT = {"segments": [{"start": 0.0, "end": 3.0}], "kept_duration": 3.0,
          "rationale": "Garde 3.0 s sur 6.0 s.",
          "decisions": [{"id": "S1", "keep": True, "type": "contenu", "by": "ia"},
                        {"id": "S2", "keep": True, "type": "digression", "by": "ia",
                         "suggested": True}]}


class CliPlanTest(unittest.TestCase):
    def plan(self, language):
        assistant = cli.Assistant("/tmp/inexistant.mp4")
        assistant.duration = 6.0
        assistant.language = language
        assistant.candidates = [{"id": "S1", "start": 0.0, "end": 3.0, "text": "un"},
                                {"id": "S2", "start": 3.0, "end": 6.0, "text": "deux"}]
        out = io.StringIO()
        with mock.patch.object(cli.pipeline, "ai_cut_plan", return_value=RESULT) as plan, \
                redirect_stdout(out):
            assistant.plan()
        return plan.call_args.kwargs["suggest_only"], out.getvalue()

    def test_arabic_plan_only_suggests_ai_cuts(self):
        suggest, out = self.plan("ar")
        self.assertTrue(suggest)
        self.assertIn("S2", out)
        self.assertIn("suggestion IA : digression", out)

    def test_french_plan_applies_ai_cuts(self):
        suggest, _ = self.plan("fr")
        self.assertFalse(suggest)


if __name__ == "__main__":
    unittest.main()
