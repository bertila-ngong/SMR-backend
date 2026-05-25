from allauth.account import views as allauth_account_views
from allauth.mfa.base import views as allauth_mfa_views
from allauth.socialaccount import views as allauth_social_account_views
from allauth.urls import build_provider_urlpatterns
from django.conf.urls import include
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import path
from django.urls import re_path
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView
from drf_spectacular.views import SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from documents.urls import api_urlpatterns as document_api_urlpatterns
from documents.urls import public_urlpatterns as document_public_urlpatterns
from documents.views import IndexView
from paperless.consumers import StatusConsumer
from paperless.views import ApplicationConfigurationViewSet
from paperless.views import DisconnectSocialAccountView
from paperless.views import FaviconView
from paperless.views import GenerateAuthTokenView
from paperless.views import GroupViewSet
from paperless.views import PaperlessObtainAuthTokenView
from paperless.views import ProfileView
from paperless.views import SocialAccountProvidersView
from paperless.views import TOTPView
from paperless.views import UserViewSet
from paperless_mail.urls import api_urlpatterns as mail_api_urlpatterns

api_router = DefaultRouter()
api_router.register(r"users", UserViewSet, basename="users")
api_router.register(r"groups", GroupViewSet, basename="groups")
api_router.register(r"config", ApplicationConfigurationViewSet)

auth_urlpatterns = [
    re_path(
        "^auth/",
        include(
            (
                [
                    path("login/", allauth_account_views.login, name="login"),
                    path("logout/", allauth_account_views.logout, name="logout"),
                ],
                "rest_framework",
            ),
            namespace="rest_framework",
        ),
    ),
    re_path("^auth/headless/", include("allauth.headless.urls")),
    path("token/", PaperlessObtainAuthTokenView.as_view()),
]

profile_urlpatterns = [
    re_path(
        "^profile/",
        include(
            [
                re_path("^$", ProfileView.as_view(), name="profile_view"),
                path(
                    "generate_auth_token/",
                    GenerateAuthTokenView.as_view(),
                ),
                path(
                    "disconnect_social_account/",
                    DisconnectSocialAccountView.as_view(),
                ),
                path(
                    "social_account_providers/",
                    SocialAccountProvidersView.as_view(),
                ),
                path("totp/", TOTPView.as_view(), name="totp_view"),
            ],
        ),
    ),
]

schema_urlpatterns = [
    re_path(
        "^schema/",
        include(
            [
                re_path("^$", SpectacularAPIView.as_view(), name="schema"),
                re_path(
                    "^view/",
                    SpectacularSwaggerView.as_view(),
                    name="swagger-ui",
                ),
            ],
        ),
    ),
]

api_urlpatterns = [
    *auth_urlpatterns,
    *profile_urlpatterns,
    *schema_urlpatterns,
    *document_api_urlpatterns,
    *mail_api_urlpatterns,
    re_path("^$", RedirectView.as_view(url="schema/view/")),
    *api_router.urls,
]

account_urlpatterns = [
    path("login/", allauth_account_views.login, name="account_login"),
    path("logout/", allauth_account_views.logout, name="account_logout"),
    path("signup/", allauth_account_views.signup, name="account_signup"),
    path(
        "account_inactive/",
        allauth_account_views.account_inactive,
        name="account_inactive",
    ),
    path(
        "password/",
        include(
            [
                path(
                    "reset/",
                    allauth_account_views.password_reset,
                    name="account_reset_password",
                ),
                path(
                    "reset/done/",
                    allauth_account_views.password_reset_done,
                    name="account_reset_password_done",
                ),
                path(
                    "reset/key/done/",
                    allauth_account_views.password_reset_from_key_done,
                    name="account_reset_password_from_key_done",
                ),
            ],
        ),
    ),
    re_path(
        r"^confirm-email/(?P<key>[-:\w]+)/$",
        allauth_account_views.ConfirmEmailView.as_view(),
        name="account_confirm_email",
    ),
    re_path(
        r"^password/reset/key/(?P<uidb36>[0-9A-Za-z]+)-(?P<key>.+)/$",
        allauth_account_views.password_reset_from_key,
        name="account_reset_password_from_key",
    ),
    path(
        "3rdparty/",
        include(
            [
                path(
                    "login/cancelled/",
                    allauth_social_account_views.login_cancelled,
                    name="socialaccount_login_cancelled",
                ),
                path(
                    "login/error/",
                    allauth_social_account_views.login_error,
                    name="socialaccount_login_error",
                ),
                path(
                    "signup/",
                    allauth_social_account_views.signup,
                    name="socialaccount_signup",
                ),
            ],
        ),
    ),
    *build_provider_urlpatterns(),
    path(
        "2fa/authenticate/",
        allauth_mfa_views.authenticate,
        name="mfa_authenticate",
    ),
]

urlpatterns = [
    re_path(r"^api/", include(api_urlpatterns)),
    *document_public_urlpatterns,
    re_path(r"^favicon.ico$", FaviconView.as_view(), name="favicon"),
    re_path(r"admin/", admin.site.urls),
    path("accounts/", include(account_urlpatterns)),
    re_path(
        r".*",
        login_required(ensure_csrf_cookie(IndexView.as_view())),
        name="base",
    ),
]

websocket_urlpatterns = [
    path("ws/status/", StatusConsumer.as_asgi()),
]

admin.site.site_header = "Paperless-ngx"
admin.site.site_title = "Paperless-ngx"
admin.site.index_title = _("Paperless-ngx administration")
