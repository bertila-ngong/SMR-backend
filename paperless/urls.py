from django.contrib import admin
from django.urls import include
from django.urls import path
from django.urls import re_path
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.routers import DefaultRouter

from documents.urls import api_urlpatterns as document_api_urlpatterns
from documents.urls import public_urlpatterns as document_public_urlpatterns
from documents.views import IndexView
from paperless.views import GroupViewSet
from paperless.views import PaperlessObtainAuthTokenView
from paperless.views import ProfileView
from paperless.views import UserViewSet

api_router = DefaultRouter()
api_router.register(r"users", UserViewSet, basename="users")
api_router.register(r"groups", GroupViewSet, basename="groups")

api_urlpatterns = [
    path("token/", PaperlessObtainAuthTokenView.as_view(), name="api_token"),
    path("profile/", ProfileView.as_view(), name="profile"),
    *document_api_urlpatterns,
    *api_router.urls,
]

urlpatterns = [
    re_path(r"^api/", include(api_urlpatterns)),
    *document_public_urlpatterns,
    re_path(r"admin/", admin.site.urls),
    re_path(r".*", ensure_csrf_cookie(IndexView.as_view()), name="frontend"),
]

websocket_urlpatterns = []

admin.site.site_header = "UB Record Management"
admin.site.site_title = "UB Record Management"
admin.site.index_title = "Administration"
