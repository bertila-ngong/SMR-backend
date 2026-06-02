from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework.authtoken.serializers import AuthTokenSerializer

from documents.models import StudentProfile
from documents.student_notifications import send_student_credentials_email


class PasswordField(serializers.CharField):
    def to_representation(self, value):
        return "********"


class PasswordValidationMixin:
    def _has_real_password(self, value: str | None) -> bool:
        return bool(value) and value.replace("*", "") != ""

    def validate_password(self, value: str) -> str:
        if not self._has_real_password(value):
            return value
        validate_password(value, self.instance)
        return value


class PaperlessAuthTokenSerializer(AuthTokenSerializer):
    pass


class UserSerializer(PasswordValidationMixin, serializers.ModelSerializer[User]):
    password = PasswordField(required=False, write_only=True)
    is_student = serializers.BooleanField(required=False)
    matricule = serializers.CharField(required=False, allow_blank=True, max_length=64)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    password_change_required = serializers.BooleanField(required=False, default=True)
    user_permissions = serializers.SlugRelatedField(
        many=True,
        queryset=Permission.objects.exclude(content_type__app_label="admin"),
        slug_field="codename",
        required=False,
    )
    inherited_permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "password",
            "first_name",
            "last_name",
            "date_joined",
            "is_staff",
            "is_active",
            "is_superuser",
            "groups",
            "user_permissions",
            "inherited_permissions",
            "is_student",
            "matricule",
            "date_of_birth",
            "password_change_required",
        )

    def get_inherited_permissions(self, obj) -> list[str]:
        return obj.get_group_permissions()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        profile = getattr(instance, "student_profile", None)
        data["is_student"] = profile is not None
        data["matricule"] = profile.matricule if profile else ""
        data["date_of_birth"] = profile.date_of_birth if profile else None
        data["password_change_required"] = (
            profile.password_change_required if profile else False
        )
        return data

    def _pop_student_profile_data(self, validated_data):
        return {
            "is_student": validated_data.pop("is_student", None),
            "matricule": validated_data.pop("matricule", ""),
            "date_of_birth": validated_data.pop("date_of_birth", None),
            "password_change_required": validated_data.pop(
                "password_change_required",
                True,
            ),
        }

    def _ensure_student_permissions(self, user: User) -> None:
        permissions = Permission.objects.filter(
            codename__in=[
                "add_document",
                "view_document",
                "change_document",
                "view_documenttype",
            ],
        )
        user.user_permissions.add(*permissions)

    def _save_student_profile(self, user: User, profile_data: dict) -> None:
        if profile_data["is_student"] is None:
            return
        if not profile_data["is_student"]:
            profile = getattr(user, "student_profile", None)
            if profile:
                profile.delete()
            return

        matricule = profile_data["matricule"] or user.username
        user.username = matricule
        user.is_staff = False
        user.is_superuser = False
        user.save(update_fields=["username", "is_staff", "is_superuser"])
        StudentProfile.objects.update_or_create(
            user=user,
            defaults={
                "matricule": matricule,
                "date_of_birth": profile_data["date_of_birth"],
                "password_change_required": profile_data[
                    "password_change_required"
                ],
            },
        )
        self._ensure_student_permissions(user)

    def update(self, instance, validated_data):
        profile_data = self._pop_student_profile_data(validated_data)
        password = validated_data.pop("password", None)
        if self._has_real_password(password):
            instance.set_password(password)
        user = super().update(instance, validated_data)
        self._save_student_profile(user, profile_data)
        return user

    def create(self, validated_data):
        profile_data = self._pop_student_profile_data(validated_data)
        groups = validated_data.pop("groups", None)
        user_permissions = validated_data.pop("user_permissions", None)
        password = validated_data.pop("password", None)
        if profile_data["is_student"]:
            validated_data["username"] = (
                profile_data["matricule"] or validated_data.get("username", "")
            )
            validated_data["is_staff"] = False
            validated_data["is_superuser"] = False
        user = User.objects.create(**validated_data)
        if groups:
            user.groups.set(groups)
        if user_permissions:
            user.user_permissions.set(user_permissions)
        if self._has_real_password(password):
            user.set_password(password)
        user.save()
        self._save_student_profile(user, profile_data)
        if profile_data["is_student"] and self._has_real_password(password):
            send_student_credentials_email(user, password)
        return user


class GroupSerializer(serializers.ModelSerializer[Group]):
    permissions = serializers.SlugRelatedField(
        many=True,
        queryset=Permission.objects.exclude(content_type__app_label="admin"),
        slug_field="codename",
    )

    class Meta:
        model = Group
        fields = ("id", "name", "permissions")


class ProfileSerializer(PasswordValidationMixin, serializers.ModelSerializer[User]):
    password = PasswordField(required=False, write_only=True)
    is_student = serializers.SerializerMethodField()
    matricule = serializers.SerializerMethodField()
    password_change_required = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_superuser",
            "is_student",
            "matricule",
            "password_change_required",
            "password",
        )

    def get_is_student(self, user: User) -> bool:
        return hasattr(user, "student_profile")

    def get_matricule(self, user: User) -> str:
        profile = getattr(user, "student_profile", None)
        return profile.matricule if profile else ""

    def get_password_change_required(self, user: User) -> bool:
        profile = getattr(user, "student_profile", None)
        return bool(profile and profile.password_change_required)
