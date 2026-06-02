from collections import OrderedDict
from typing import Any

from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.db.models.functions import Lower
from django.http import HttpResponseForbidden
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.filters import OrderingFilter
from rest_framework.generics import GenericAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.viewsets import ModelViewSet

from documents.permissions import PaperlessObjectPermissions
from paperless.filters import GroupFilterSet
from paperless.filters import UserFilterSet
from paperless.serialisers import GroupSerializer
from paperless.serialisers import PaperlessAuthTokenSerializer
from paperless.serialisers import ProfileSerializer
from paperless.serialisers import UserSerializer


class PaperlessObtainAuthTokenView(ObtainAuthToken):
    serializer_class = PaperlessAuthTokenSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        token, _created = Token.objects.get_or_create(user=user)
        return Response(
            {
                "token": token.key,
                "user": ProfileSerializer(user).data,
            },
        )


class StandardPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100000

    def get_paginated_response(self, data):
        return Response(
            OrderedDict(
                [
                    ("count", self.page.paginator.count),
                    ("next", self.get_next_link()),
                    ("previous", self.get_previous_link()),
                    ("results", data),
                ],
            ),
        )


class UserViewSet(ModelViewSet[User]):
    queryset = User.objects.exclude(
        username__in=["consumer", "AnonymousUser"],
    ).order_by(Lower("username"))
    serializer_class = UserSerializer
    pagination_class = StandardPagination
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)
    filter_backends = (DjangoFilterBackend, OrderingFilter)
    filterset_class = UserFilterSet
    ordering_fields = ("username",)

    def _cannot_change_staff_status(self, request, target: User | None = None) -> bool:
        if request.user.is_superuser:
            return False
        requested_staff = {
            key: request.data.get(key)
            for key in ("is_staff", "is_superuser")
            if key in request.data
        }
        if target is None:
            return bool(
                requested_staff.get("is_staff") or requested_staff.get("is_superuser"),
            )
        return any(str(value) != str(getattr(target, key)) for key, value in requested_staff.items())

    def create(self, request, *args, **kwargs):
        if self._cannot_change_staff_status(request):
            return HttpResponseForbidden(
                "Staff and superuser status can only be granted by a superuser",
            )
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        user_to_update = self.get_object()
        if not request.user.is_superuser and user_to_update.is_superuser:
            return HttpResponseForbidden(
                "Superusers can only be modified by other superusers",
            )
        if self._cannot_change_staff_status(request, user_to_update):
            return HttpResponseForbidden(
                "Staff and superuser status can only be changed by a superuser",
            )
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        user_to_delete = self.get_object()
        if not request.user.is_superuser and user_to_delete.is_superuser:
            return HttpResponseForbidden(
                "Superusers can only be deleted by other superusers",
            )
        return super().destroy(request, *args, **kwargs)


class GroupViewSet(ModelViewSet[Group]):
    queryset = Group.objects.order_by(Lower("name"))
    serializer_class = GroupSerializer
    pagination_class = StandardPagination
    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)
    filter_backends = (DjangoFilterBackend, OrderingFilter)
    filterset_class = GroupFilterSet
    ordering_fields = ("name",)


class ProfileView(GenericAPIView[Any]):
    permission_classes = [IsAuthenticated]
    serializer_class = ProfileSerializer

    def get(self, request, *args, **kwargs):
        return Response(self.get_serializer(request.user).data)

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = request.user
        password = serializer.validated_data.pop("password", None)
        if password and password.replace("*", ""):
            user.set_password(password)
            profile = getattr(user, "student_profile", None)
            if profile is not None:
                profile.password_change_required = False
                profile.save(update_fields=["password_change_required", "updated_at"])
        for key, value in serializer.validated_data.items():
            setattr(user, key, value)
        user.save()
        return Response(self.get_serializer(user).data)
