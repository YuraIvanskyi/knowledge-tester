from decimal import Decimal

from django import template
from django.utils import formats
from django.utils.translation import gettext as _

from apps.grading.scales import fmt_number

register = template.Library()


@register.filter
def num(value):
    """Number without trailing zeros and without localisation: 2.50 -> 2.5, 3.00 -> 3."""
    if value is None or value == "":
        return ""
    return fmt_number(value)


@register.filter
def numd(value):
    """Like `num`, but for display: uses the active locale's decimal separator (2,5 in uk)."""
    if value is None or value == "":
        return ""
    return formats.number_format(Decimal(fmt_number(value)), use_l10n=True)


@register.filter
def grade_text(value):
    """Display text of a stored grade label; the built-in Pass/Fail labels are translated."""
    if value == "Pass":
        return _("Pass")
    if value == "Fail":
        return _("Fail")
    return value


@register.filter
def signed(value):
    """Extra points with their sign for display: +2, +1,5, −1 (a real minus sign)."""
    if value is None or value == "":
        return ""
    number = Decimal(str(value))
    text = numd(abs(number))
    return f"+{text}" if number >= 0 else f"\u2212{text}"
