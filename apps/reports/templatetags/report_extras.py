from django import template

from apps.grading.scales import fmt_number

register = template.Library()


@register.filter
def num(value):
    """Number without trailing zeros and without localisation: 2.50 -> 2.5, 3.00 -> 3."""
    if value is None or value == "":
        return ""
    return fmt_number(value)
