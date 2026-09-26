"""Portable behavior and CLI checks for the skill's deterministic helpers."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from measure_text import measure_text
from summarize_samples import summarize_samples, summarize_series


class TextTests(unittest.TestCase):
    def test_decoded_unicode_spaces_and_punctuation(self):
        # Unicode escapes become visible characters before the helper receives text.
        bullets = json.loads('["Built caf\\u00e9 \\u2014 saved 31.8%.", "Reduced tokens & memory."]')
        result = measure_text(bullets, expected_count=2)
        self.assertTrue(result["valid"])
        self.assertEqual(result["bullets"][0]["characters"], 25)
        self.assertEqual(result["bullets"][0]["words"], 5)
        self.assertEqual(result["bullets"][1]["characters"], 24)

    def test_counts_codepoints_not_graphemes_or_markup(self):
        result = measure_text(["e\u0301", r"31.8\%"])
        self.assertEqual(result["bullets"][0]["characters"], 2)
        self.assertEqual(result["bullets"][1]["characters"], 6)

    def test_two_and_three_bullet_counts(self):
        self.assertTrue(measure_text(["One", "Two"], 2)["valid"])
        self.assertTrue(measure_text({"bullets": ["One", "Two", "Three"]}, 3)["valid"])
        self.assertFalse(measure_text(["One", "Two"], 3)["valid"])

    def test_character_range_is_advisory(self):
        result = measure_text(["short", "x" * 230, "x" * 300])
        self.assertTrue(result["valid"])
        self.assertEqual([item["character_range"] for item in result["bullets"]], ["below", "within", "above"])

    def test_reject_non_single_line_or_padded_text(self):
        for text in ("line\nbreak", "line\rbreak", "a\tb", " leading", "trailing ", "", "a\u2028b", "a\x00b"):
            with self.subTest(text=repr(text)):
                self.assertFalse(measure_text([text])["valid"])

    def test_schema_errors(self):
        for payload in ([], "not a list", {}, {"bullets": "no"}, [True], [3]):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    measure_text(payload)


class SampleTests(unittest.TestCase):
    def test_outlier_median_and_nearest_rank_p95(self):
        values = [1] * 18 + [2, 1000]
        result = summarize_series(values, "candidate")
        self.assertEqual(result, {"n": 20, "median": 1.0, "p95": 2.0, "min": 1.0, "max": 1000.0})

    def test_unrounded_even_median_and_formula(self):
        result = summarize_samples({"baseline": [2, 4], "candidate": [1, 2]})
        self.assertEqual(result["candidate"]["median"], 1.5)
        self.assertEqual(result["comparison"]["candidate_to_baseline_ratio"], 0.5)
        self.assertEqual(result["comparison"]["relative_change_percent"], -50)
        self.assertEqual(result["comparison"]["reduction_percent"], 50)

    def test_negative_reduction_not_clamped(self):
        result = summarize_samples({"baseline": [3], "candidate": [4]})
        self.assertAlmostEqual(result["comparison"]["reduction_percent"], -100 / 3)

    def test_ratio_of_medians_not_median_of_pairwise_ratios(self):
        result = summarize_samples({"baseline": [1, 10, 100], "candidate": [2, 90, 50]})
        self.assertEqual(result["comparison"]["candidate_to_baseline_ratio"], 5)

    def test_zero_baseline_has_null_comparison_and_reason(self):
        result = summarize_samples({"baseline": [0, 0, 1], "candidate": [1, 2, 3]})
        self.assertIsNone(result["comparison"]["reduction_percent"])
        self.assertIn("zero", result["comparison"]["unavailable_reason"])

    def test_absolute_result(self):
        result = summarize_samples({"candidate": [3, 1, 2]})
        self.assertEqual(result["candidate"]["median"], 2)
        self.assertIsNone(result["baseline"])
        self.assertIsNone(result["comparison"]["candidate_to_baseline_ratio"])

    def test_invalid_numbers_and_shapes(self):
        for values in ([], [float("nan")], [float("inf")], [float("-inf")], [-1], [True], ["3"], [None], [10 ** 1000], "3"):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    summarize_samples({"candidate": values})
        with self.assertRaises(ValueError):
            summarize_samples({"baseline": [1]})

    def test_large_finite_median_and_comparison_overflow(self):
        result = summarize_series([1e308, 1e308], "candidate")
        self.assertEqual(result["median"], 1e308)
        result = summarize_samples({"baseline": [1e-308], "candidate": [1e308]})
        self.assertIsNone(result["comparison"]["reduction_percent"])
        self.assertIn("finite", result["comparison"]["unavailable_reason"])


class CliTests(unittest.TestCase):
    def run_cli(self, script, payload, *args):
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / script), "-", *args],
            input=payload.encode("utf-8"), capture_output=True, check=False,
        )

    def test_text_stdin_success_and_expected_count_failure(self):
        raw = json.dumps(["Built a café.", "Reduced work."])
        passed = self.run_cli("measure_text.py", raw, "--expected-count", "2")
        self.assertEqual(passed.returncode, 0, passed.stderr)
        failed = self.run_cli("measure_text.py", raw, "--expected-count", "3")
        self.assertEqual(failed.returncode, 2)
        self.assertFalse(json.loads(failed.stdout)["valid"])

    def test_utf8_bom_file_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bullets.json"
            path.write_text(json.dumps(["Built a café.", "Reduced work."], ensure_ascii=False), encoding="utf-8-sig")
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "measure_text.py"), str(path)], capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_json_and_sample_validation_errors(self):
        for script, raw in (("measure_text.py", "{"), ("summarize_samples.py", '{"candidate":[NaN]}'), ("summarize_samples.py", '{"candidate":[]}')):
            with self.subTest(script=script, raw=raw):
                result = self.run_cli(script, raw)
                self.assertEqual(result.returncode, 2)
                self.assertIn("error", json.loads(result.stderr))
                self.assertNotIn(b"Traceback", result.stderr)

    def test_sample_cli_outputs_comparison(self):
        result = self.run_cli("summarize_samples.py", '{"baseline":[10,12,11],"candidate":[6,7,8]}')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertAlmostEqual(json.loads(result.stdout)["comparison"]["reduction_percent"], 400 / 11)


if __name__ == "__main__":
    unittest.main()
