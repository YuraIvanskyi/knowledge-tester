"""Settings for the pytest run: English by default so existing tests keep asserting English text.

Tests of Ukrainian behaviour select it explicitly (cookie, ``translation.override("uk")``
or ``settings.LANGUAGE_CODE``).
"""

from .dev import *  # noqa: F401,F403

LANGUAGE_CODE = "en"
