"""Make Ukrainian the real default UI language."""

from django.conf import settings


class DefaultLanguageMiddleware:
    """Ignore the browser's Accept-Language until the user has chosen a language.

    Phones with an English browser would otherwise get English although the app default is
    Ukrainian. Once the ``set_language`` view has stored the language cookie, the header is left
    alone (and the cookie wins anyway). Must be placed before ``LocaleMiddleware``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.LANGUAGE_COOKIE_NAME not in request.COOKIES:
            request.META.pop("HTTP_ACCEPT_LANGUAGE", None)
        return self.get_response(request)
