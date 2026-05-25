import django.db.models.deletion
from django.conf import settings
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0020_drop_celery_results"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StudentRecord",
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
                    "data",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        verbose_name="student record data",
                    ),
                ),
                (
                    "confidence",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        verbose_name="field confidence",
                    ),
                ),
                (
                    "raw_text",
                    models.TextField(
                        blank=True,
                        default="",
                        verbose_name="raw extracted text",
                    ),
                ),
                (
                    "extraction_source",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=32,
                        verbose_name="extraction source",
                    ),
                ),
                (
                    "extraction_error",
                    models.TextField(
                        blank=True,
                        default="",
                        verbose_name="extraction error",
                    ),
                ),
                (
                    "needs_review",
                    models.BooleanField(default=True, verbose_name="needs review"),
                ),
                (
                    "extracted_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="date extracted",
                    ),
                ),
                (
                    "reviewed_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="date reviewed",
                    ),
                ),
                (
                    "document",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="student_record",
                        to="documents.document",
                        verbose_name="document",
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_student_records",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="reviewed by",
                    ),
                ),
            ],
            options={
                "verbose_name": "student record",
                "verbose_name_plural": "student records",
            },
        ),
    ]
