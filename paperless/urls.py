from django.contrib import admin
from django.urls import include
from django.urls import path
from django.urls import re_path
from rest_framework.routers import DefaultRouter

from documents.urls import api_urlpatterns as document_api_urlpatterns
from documents.urls import public_urlpatterns as document_public_urlpatterns
from paperless.views import GroupViewSet
from paperless.views import PaperlessObtainAuthTokenView
from paperless.views import ProfileView
from paperless.views import StudentsViewSet
from paperless.views import UserViewSet

api_router = DefaultRouter()
api_router.register(r"users", UserViewSet, basename="users")
api_router.register(r"groups", GroupViewSet, basename="groups")
api_router.register(r"students", StudentsViewSet, basename="students")

api_urlpatterns = [
    path("token/", PaperlessObtainAuthTokenView.as_view(), name="api_token"),
    path("profile/", ProfileView.as_view(), name="profile"),
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
