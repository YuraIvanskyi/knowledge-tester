from decimal import Decimal as D

import pytest

from apps.grading.scales import grade_label


@pytest.mark.parametrize(
    ("grading", "score", "max_score", "percent", "expected"),
    [
        ({"scale": "percent"}, D("7.5"), D(9), D("83.3"), "83.3 %"),
        ({}, D(1), D(2), D("50.0"), "50.0 %"),
        (None, D(1), D(2), D("50.0"), "50.0 %"),
        ({"scale": "points"}, D("7.50"), D("9.00"), D("83.3"), "7.5 / 9"),
        ({"scale": "points"}, D(0), D(9), D("0.0"), "0 / 9"),
        ({"scale": "pass_fail"}, D(5), D(10), D("50.0"), "Pass"),
        ({"scale": "pass_fail"}, D(4), D(10), D("40.0"), "Fail"),
        ({"scale": "pass_fail", "pass_percent": 60}, D(5), D(10), D("50.0"), "Fail"),
        ({"scale": "pass_fail", "pass_percent": 60}, D(6), D(10), D("60.0"), "Pass"),
        # ua_12: twelve equal bands, band m starts at (m - 1) * 100 / 12
        ({"scale": "ua_12"}, D(0), D(10), D("0.0"), "1"),
        ({"scale": "ua_12"}, D(1), D(12), D("8.3"), "1"),
        ({"scale": "ua_12"}, D(1), D(12), D("8.4"), "2"),
        ({"scale": "ua_12"}, D(1), D(2), D("50.0"), "7"),
        ({"scale": "ua_12"}, D(1), D(2), D("91.6"), "11"),
        ({"scale": "ua_12"}, D(1), D(2), D("91.7"), "12"),
        ({"scale": "ua_12"}, D(1), D(1), D("100.0"), "12"),
        # five_point defaults and editable thresholds
        ({"scale": "five_point"}, D(1), D(1), D("90.0"), "5"),
        ({"scale": "five_point"}, D(1), D(1), D("89.9"), "4"),
        ({"scale": "five_point"}, D(1), D(1), D("60.0"), "3"),
        ({"scale": "five_point"}, D(1), D(1), D("59.9"), "2"),
        (
            {
                "scale": "five_point",
                "thresholds": [
                    {"min_percent": 0, "label": "2"},
                    {"min_percent": 50, "label": "3"},
                    {"min_percent": 70, "label": "4"},
                    {"min_percent": 85, "label": "5"},
                ],
            },
            D(1),
            D(1),
            D("70.0"),
            "4",
        ),
        # custom thresholds (any order, top-down evaluation)
        (
            {
                "scale": "custom",
                "thresholds": [
                    {"min_percent": 0, "label": "Retake"},
                    {"min_percent": 80, "label": "Merit"},
                    {"min_percent": 50, "label": "Pass"},
                ],
            },
            D(1),
            D(1),
            D("79.9"),
            "Pass",
        ),
        (
            {"scale": "custom", "thresholds": [{"min_percent": 50, "label": "Pass"}]},
            D(1),
            D(1),
            D("10.0"),
            "",
        ),
        # nothing gradable
        ({"scale": "percent"}, D(0), D(0), None, ""),
    ],
)
def test_grade_label(grading, score, max_score, percent, expected):
    assert grade_label(grading, score, max_score, percent) == expected
