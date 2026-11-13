"""Settings for the pytest run: English by default so existing tests keep asserting English text.

Tests of Ukrainian behaviour select it explicitly (cookie, ``translation.override("uk")``
or ``settings.LANGUAGE_CODE``).
"""

from .dev import *  # noqa: F401,F403

LANGUAGE_CODE = "en"

# Real password hashing (PBKDF2, hundreds of thousands of rounds) costs about a second per user
# created, and nearly every test creates one: the suite took 25+ minutes instead of a few.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
