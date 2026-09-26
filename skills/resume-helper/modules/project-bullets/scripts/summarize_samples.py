#!/usr/bin/env python3
"""Summarize recorded numeric samples without running benchmark commands."""

import argparse
import json
import math
from pathlib import Path
import sys


def summarize_series(values, label):
    if not isinstance(values, list) or not values:
        raise ValueError(f"'{label}' must be a nonempty array of finite, nonnegative numbers.")
    normalized = []
    for index, value in enumerate(values, start=1):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"'{label}' sample {index} must be a number, not a boolean or string.")
        try:
            number = float(value)
        except OverflowError as exc:
            raise ValueError(f"'{label}' sample {index} exceeds finite floating-point range.") from exc
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"'{label}' sample {index} must be finite and nonnegative.")
        normalized.append(number)
    ordered = sorted(normalized)
    count = len(ordered)
    midpoint = count // 2
    # This midpoint avoids overflow when both central samples are very large.
    median = ordered[midpoint] if count % 2 else ordered[midpoint - 1] + (ordered[midpoint] - ordered[midpoint - 1]) / 2
    return {
        "n": count,
        "median": median,
        "p95": ordered[math.ceil(0.95 * count) - 1],
        "min": ordered[0],
        "max": ordered[-1],
    }


def summarize_samples(payload):
    """Calculate a ratio of medians, not a median of per-pair changes."""
    if not isinstance(payload, dict) or "candidate" not in payload:
        raise ValueError("Input must be an object containing a 'candidate' sample array.")
    candidate = summarize_series(payload["candidate"], "candidate")
    baseline = summarize_series(payload["baseline"], "baseline") if "baseline" in payload else None
    comparison = {
        "candidate_to_baseline_ratio": None,
        "relative_change_percent": None,
        "reduction_percent": None,
        "unavailable_reason": None,
    }
    if baseline is None:
        comparison["unavailable_reason"] = "No baseline was supplied; report the absolute candidate measurement."
    elif baseline["median"] == 0:
        comparison["unavailable_reason"] = "The baseline median is zero; relative change has no defined denominator."
    else:
        base = baseline["median"]
        current = candidate["median"]
        ratio = current / base
        relative_change = ((current - base) / base) * 100
        if all(math.isfinite(value) for value in (ratio, relative_change)):
            comparison.update({
                "candidate_to_baseline_ratio": ratio,
                "relative_change_percent": relative_change,
                "reduction_percent": -relative_change,
            })
        else:
            comparison["unavailable_reason"] = "The comparison exceeds finite floating-point range."
    return {
        "baseline": baseline,
        "candidate": candidate,
        "comparison": comparison,
        "method": {
            "percentile": "p95 uses nearest rank: sorted_samples[ceil(0.95 * n) - 1].",
            "comparison": "Ratio of medians; relative change = (candidate median - baseline median) / baseline median * 100; reduction is its negative.",
            "precision": "Calculations use unrounded binary floating-point values; round only when writing the final claim.",
        },
        "interpretation": "A positive reduction is favorable only for lower-is-better measures such as time, memory, or work. "
        "Negative reductions are retained. This summary does not establish a speedup, fairness, correctness, statistical significance, or real-world impact.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Summarize saved samples from a UTF-8 JSON file or stdin ('-'). "
        "Input: {\"baseline\": [10, 12, 11], \"candidate\": [6, 7, 8]}; "
        "baseline may be omitted for absolute results. Use identical units and comparable workloads. "
        "This tool does not run commands or validate a benchmark's design."
    )
    parser.add_argument("input", help="UTF-8 JSON path, or '-' for stdin")
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig") if args.input == "-" else Path(args.input).read_text(encoding="utf-8-sig")
        report = summarize_samples(json.loads(raw))
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
