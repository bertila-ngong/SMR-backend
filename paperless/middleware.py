from django.conf import settings

from paperless import version


class ApiVersionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if hasattr(request, "user") and request.user and request.user.is_authenticated:
            versions = settings.REST_FRAMEWORK.get("ALLOWED_VERSIONS", [])
            if versions:
                response["X-Api-Version"] = versions[-1]
            response["X-Version"] = version.__full_version_str__

        return response
