import django.db.models.deletion
from django.conf import settings
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0022_studentrecord_extraction_metadata"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StudentProfile",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "matricule",
                    models.CharField(
                        max_length=64,
                        unique=True,
                        verbose_name="matricule",
                    ),
                ),
                (
                    "date_of_birth",
                    models.DateField(
                        blank=True,
                        null=True,
                        verbose_name="date of birth",
                    ),
                ),
                (
                    "password_change_required",
                    models.BooleanField(
                        default=True,
                        verbose_name="password change required",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="date created",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="date updated",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="student_profile",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="user",
                    ),
                ),
            ],
            options={
                "verbose_name": "student profile",
                "verbose_name_plural": "student profiles",
            },
        ),
        migrations.AddField(
            model_name="studentrecord",
            name="approved_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="date approved",
            ),
        ),
        migrations.AddField(
            model_name="studentrecord",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("pending", "Pending review"),
                    ("approved", "Approved"),
                    ("changes_requested", "Changes requested"),
                ],
                default="draft",
                max_length=32,
                verbose_name="status",
            ),
        ),
        migrations.AddField(
            model_name="studentrecord",
            name="submitted_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="date submitted",
            ),
        ),
        migrations.AddField(
            model_name="studentrecord",
            name="student",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="student_records",
                to=settings.AUTH_USER_MODEL,
                verbose_name="student",
            ),
        ),
    ]
