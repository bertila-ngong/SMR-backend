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


class StudentSerializer(PasswordValidationMixin, serializers.Serializer):
    """Serializer for creating and managing student accounts."""

    id = serializers.IntegerField(read_only=True)
    user = serializers.IntegerField(read_only=True, source="user.id")
    username = serializers.CharField(max_length=150, write_only=True)
    password = PasswordField(required=False, write_only=True)
    email = serializers.EmailField(required=False)
    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False)
    matricule = serializers.CharField(max_length=64)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    password_change_required = serializers.BooleanField(
        default=True,
        write_only=True,
    )
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def validate_username(self, value: str) -> str:
        """Ensure username is unique."""
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already exists.")
        return value

    def validate_matricule(self, value: str) -> str:
        """Ensure matricule is unique."""
        instance = self.instance
        qs = StudentProfile.objects.filter(matricule=value)
        if instance:
            qs = qs.exclude(user_id=instance.user_id)
        if qs.exists():
            raise serializers.ValidationError("Matricule already exists.")
        return value

    def validate_password(self, value: str) -> str:
        """Validate password strength if provided."""
        if not self._has_real_password(value):
            return value
        validate_password(value)
        return value

    def create(self, validated_data):
        """Create a new user and student profile."""
        username = validated_data.pop("username")
        password = validated_data.pop("password", None)
        matricule = validated_data.pop("matricule")
        password_change_required = validated_data.pop("password_change_required", True)
        email = validated_data.pop("email", "")
        first_name = validated_data.pop("first_name", "")
        last_name = validated_data.pop("last_name", "")
        date_of_birth = validated_data.pop("date_of_birth", None)

        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        if password:
            user.set_password(password)
        user.save()

        # Create student profile
        student_profile = StudentProfile.objects.create(
            user=user,
            matricule=matricule,
            date_of_birth=date_of_birth,
            password_change_required=password_change_required,
        )

        # Ensure student has permission to add documents
        # (also done via signal handler, but this ensures it's always set)
        self._ensure_student_permissions(user)

        # Send credentials email if password was set
        if password:
            send_student_credentials_email(user, password)

        return student_profile

    def _ensure_student_permissions(self, user: User) -> None:
        """Assign required permissions to a student user."""
        permissions = Permission.objects.filter(
            codename__in=["add_document", "view_document", "change_document", "view_documenttype"],
        )
        user.user_permissions.add(*permissions)

    def update(self, instance, validated_data):
        """Update an existing student profile."""
        password = validated_data.pop("password", None)

        # Update user fields
        user = instance.user
        for field in ["email", "first_name", "last_name"]:
            if field in validated_data:
                setattr(user, field, validated_data.pop(field))
        if password:
            user.set_password(password)
        user.save()

        # Update student profile fields
        for field in ["matricule", "date_of_birth", "password_change_required"]:
            if field in validated_data:
                setattr(instance, field, validated_data[field])
        instance.save()

        # Ensure permissions are set
        self._ensure_student_permissions(user)

        return instance

    def to_representation(self, instance):
        """Return student data with related user info."""
        return {
            "id": instance.id,
            "user": instance.user.id,
            "username": instance.user.username,
            "email": instance.user.email,
            "first_name": instance.user.first_name,
            "last_name": instance.user.last_name,
            "matricule": instance.matricule,
            "date_of_birth": instance.date_of_birth,
            "password_change_required": instance.password_change_required,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
        }
