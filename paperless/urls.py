from django.contrib import admin
from django.urls import include
from django.urls import path
from django.urls import re_path
from rest_framework.routers import DefaultRouter

from documents.urls import api_urlpatterns as document_api_urlpatterns
from documents.urls import public_urlpatterns as document_public_urlpatterns
from documents.views import DocumentTypeViewSet
from documents.views import DocumentViewSet
from documents.views import PaperlessTaskViewSet
from paperless.views import GroupViewSet
from paperless.views import PaperlessObtainAuthTokenView
from paperless.views import ProfileView
from paperless.views import StudentsViewSet
from paperless.views import UiSettingsView
from paperless.views import UserViewSet

api_router = DefaultRouter()
api_router.register(r"users", UserViewSet, basename="users")
api_router.register(r"groups", GroupViewSet, basename="groups")
api_router.register(r"students", StudentsViewSet, basename="students")
api_router.register(r"document_types", DocumentTypeViewSet, basename="document_types")
api_router.register(r"tasks", PaperlessTaskViewSet, basename="tasks")
api_router.register(r"documents", DocumentViewSet, basename="documents")

api_urlpatterns = [
    path("token/", PaperlessObtainAuthTokenView.as_view(), name="api_token"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("ui_settings/", UiSettingsView.as_view(), name="ui_settings"),
    *document_api_urlpatterns,
    *api_router.urls,
]

urlpatterns = [
    path("admin/", admin.site.urls),
    re_path(r"^api/", include(api_urlpatterns)),
    *document_public_urlpatterns,
]

websocket_urlpatterns = []

admin.site.site_header = "UB Record Management"
admin.site.site_title = "UB Record Management"
admin.site.index_title = "Administration"
