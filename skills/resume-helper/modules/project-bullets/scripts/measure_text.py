#!/usr/bin/env python3
"""Count plain visible resume bullet text; do not parse Markdown or LaTeX."""

import argparse
import json
from pathlib import Path
import sys


def measure_text(payload, expected_count=None, min_chars=210, max_chars=245):
    """Return counts and diagnostics, keeping length guidance advisory."""
    if isinstance(payload, dict):
        if "bullets" not in payload:
            raise ValueError("Object input must contain a 'bullets' array.")
        bullets = payload["bullets"]
    else:
        bullets = payload
    if not isinstance(bullets, list) or not bullets:
        raise ValueError("Input must be a nonempty array of plain visible bullet strings.")
    if expected_count not in (None, 2, 3):
        raise ValueError("expected_count must be 2 or 3 when supplied.")
    if min_chars < 1 or max_chars < min_chars:
        raise ValueError("Character range must satisfy 1 <= min_chars <= max_chars.")

    errors = []
    if expected_count is not None and len(bullets) != expected_count:
        errors.append(f"Expected {expected_count} bullets; received {len(bullets)}.")
    results = []
    for index, bullet in enumerate(bullets, start=1):
        if not isinstance(bullet, str):
            raise ValueError(f"Bullet {index} must be a string.")
        problems = []
        if not bullet or not bullet.strip():
            problems.append("must not be empty or whitespace-only")
        if bullet != bullet.strip():
            problems.append("must not have leading or trailing whitespace")
        if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in bullet):
            problems.append("must not contain control characters, newlines, or tabs")
        if "\u2028" in bullet or "\u2029" in bullet:
            problems.append("must not contain Unicode line or paragraph separators")
        errors.extend(f"Bullet {index} {problem}." for problem in problems)

        count = len(bullet)
        band = "below" if count < min_chars else "above" if count > max_chars else "within"
        results.append({
            "bullet": index,
            "characters": count,
            "words": len(bullet.split()),
            "character_range": band,
            "advisories": [] if band == "within" else [
                f"Text is {band} the advisory {min_chars}-{max_chars} character range."
            ],
        })
    return {
        "valid": not errors,
        "bullet_count": len(bullets),
        "expected_count": expected_count,
        "counting": "Unicode code points, including spaces and punctuation; words split on whitespace.",
        "input_contract": "Plain visible text only. Remove markup yourself; JSON escapes are decoded before counting.",
        "layout": "Counts do not establish rendered line count or second-line occupancy.",
        "advisory_range": {"minimum": min_chars, "maximum": max_chars},
        "bullets": results,
        "errors": errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Count plain visible bullet text from a UTF-8 JSON file or stdin ('-'). "
        "Input: [\"Built ...\", \"Reduced ...\"] or {\"bullets\": [...]}. "
        "Do not supply LaTeX or Markdown markup; no markup stripping is performed."
    )
    parser.add_argument("input", help="UTF-8 JSON path, or '-' for stdin")
    parser.add_argument("--expected-count", type=int, choices=(2, 3), help="Require exactly this many bullets")
    parser.add_argument("--min-chars", type=int, default=210, help="Advisory minimum (default: 210)")
    parser.add_argument("--max-chars", type=int, default=245, help="Advisory maximum (default: 245)")
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig") if args.input == "-" else Path(args.input).read_text(encoding="utf-8-sig")
        report = measure_text(json.loads(raw), args.expected_count, args.min_chars, args.max_chars)
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
