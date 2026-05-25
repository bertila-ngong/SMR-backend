from django.urls import re_path
from rest_framework.routers import DefaultRouter

from paperless_mail.views import MailAccountViewSet
from paperless_mail.views import MailRuleViewSet
from paperless_mail.views import OauthCallbackView
from paperless_mail.views import ProcessedMailViewSet

router = DefaultRouter()
router.register(r"mail_accounts", MailAccountViewSet)
router.register(r"mail_rules", MailRuleViewSet)
router.register(r"processed_mail", ProcessedMailViewSet)

api_urlpatterns = [
    re_path(
        r"^oauth/callback/",
        OauthCallbackView.as_view(),
        name="oauth_callback",
    ),
    *router.urls,
]

urlpatterns = api_urlpatterns
