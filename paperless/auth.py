from rest_framework import authentication


class PaperlessBasicAuthentication(authentication.BasicAuthentication):
    def authenticate_header(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.lower().startswith("basic "):
            return super().authenticate_header(request)
        return authentication.TokenAuthentication.keyword
