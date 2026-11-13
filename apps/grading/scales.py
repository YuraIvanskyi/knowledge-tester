"""Grade scales (plan §10). Pure Python.

A scale maps the attempt percentage to a label through a threshold table
("percent >= min_percent gives this label"), evaluated from the top down.
"""

from __future__ import annotations

from decimal import Decimal

SCALES = ("percent", "points", "pass_fail", "ua_12", "five_point", "custom")

DEFAULT_PASS_PERCENT = Decimal(50)
# Editable via grading.thresholds when scale == "five_point".
DEFAULT_FIVE_POINT = [
    {"min_percent": 90, "label": "5"},
    {"min_percent": 75, "label": "4"},
    {"min_percent": 60, "label": "3"},
    {"min_percent": 0, "label": "2"},
]


def ua_12_thresholds() -> list[dict]:
    """Twelve equal percent bands: mark m starts at (m - 1) / 12 of the maximum.

    Not an official standard; teachers should adjust the bands to their school's policy.
    """
    return [
        {"min_percent": Decimal(100 * (m - 1)) / Decimal(12), "label": str(m)}
        for m in range(12, 0, -1)
    ]


def fmt_number(value: Decimal | int | float | str) -> str:
    """Format a number without trailing zeros: 7.50 -> "7.5", 9.00 -> "9"."""
    d = Decimal(str(value))
    if d == d.to_integral_value():
        return str(int(d))
    return format(d.normalize(), "f")


def pick_label(percent: Decimal, thresholds: list[dict]) -> str:
    """First label (highest min_percent first) whose min_percent the percentage reaches."""
    rows = sorted(
        ((Decimal(str(t["min_percent"])), str(t["label"])) for t in thresholds),
        key=lambda r: r[0],
        reverse=True,
    )
    for min_percent, label in rows:
        if percent >= min_percent:
            return label
    return ""


def grade_label(
    grading: dict | None,
    score: Decimal,
    max_score: Decimal,
    percent: Decimal | None,
) -> str:
    """Return the grade label for a result. Empty string if nothing is gradable.

    `percent` is the rounded value for display; the band is decided from score / max_score."""
    if percent is None or max_score <= 0:
        return ""
    grading = grading or {}
    scale = grading.get("scale") or "percent"
    # Bands are compared with the exact percentage: the rounded one (shown to people) would put
    # 10/12 = 83.33 % just under the 83.333... start of mark 11, and 49.96 % over a 50 % pass mark.
    exact = score * 100 / max_score
    thresholds = grading.get("thresholds")

    if scale == "points":
        return f"{fmt_number(score)} / {fmt_number(max_score)}"
    if scale == "pass_fail":
        pass_percent = Decimal(str(grading.get("pass_percent", DEFAULT_PASS_PERCENT)))
        return "Pass" if exact >= pass_percent else "Fail"
    if scale == "ua_12":
        return pick_label(exact, ua_12_thresholds())
    if scale == "five_point":
        return pick_label(exact, thresholds or DEFAULT_FIVE_POINT)
    if scale == "custom":
        return pick_label(exact, thresholds) if thresholds else f"{percent} %"
    return f"{percent} %"  # "percent" and anything unknown
