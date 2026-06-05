from datetime import datetime
from typing import Any

import magic
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from documents.models import CustomField
from documents.models import Document
from documents.models import DocumentType
from documents.models import PaperlessTask
from documents.models import SavedView
from documents.models import StudentRecord
from documents.parsers import is_mime_type_supported


class DocumentTypeSerializer(serializers.ModelSerializer):
    document_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = DocumentType
        fields = (
            "id",
            "name",
            "match",
            "matching_algorithm",
            "is_insensitive",
            "document_count",
        )


class PostDocumentSerializer(serializers.Serializer[dict[str, Any]]):
    document = serializers.FileField(write_only=True)
    title = serializers.CharField(write_only=True, required=False, allow_blank=True)
    created = serializers.DateTimeField(write_only=True, required=False, allow_null=True)
    record_type = serializers.ChoiceField(
        choices=["student_record"],
        write_only=True,
        required=False,
    )
    student_matricule = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        max_length=64,
    )

    def validate_document(self, document):
        document_data = document.file.read()
        mime_type = magic.from_buffer(document_data, mime=True)

        if not is_mime_type_supported(mime_type):
            recoverable_pdf = (
                mime_type in settings.CONSUMER_PDF_RECOVERABLE_MIME_TYPES
                and document.name.endswith(".pdf")
            )
            if not recoverable_pdf:
                raise serializers.ValidationError(
                    _("File type %(type)s not supported") % {"type": mime_type},
                )

        return document.name, document_data

    def validate_created(self, created):
        if isinstance(created, datetime):
            return created.date()
        return created


class StudentRecordSerializer(serializers.ModelSerializer[StudentRecord]):
    document_title = serializers.CharField(source="document.title", read_only=True)
    student_username = serializers.CharField(source="student.username", read_only=True)
    reviewed_by_username = serializers.CharField(
        source="reviewed_by.username",
        read_only=True,
    )

    class Meta:
        model = StudentRecord
        fields = (
            "id",
            "document",
            "document_title",
            "student",
            "student_username",
            "data",
            "confidence",
            "raw_text",
            "extraction_source",
            "extraction_error",
            "needs_review",
            "status",
            "extracted_at",
            "submitted_at",
            "reviewed_at",
            "approved_at",
            "reviewed_by",
            "reviewed_by_username",
        )
        read_only_fields = (
            "id",
            "document",
            "document_title",
            "student",
            "student_username",
            "confidence",
            "raw_text",
            "extraction_source",
            "extraction_error",
            "extracted_at",
            "status",
            "submitted_at",
            "reviewed_at",
            "approved_at",
            "reviewed_by",
            "reviewed_by_username",
        )


class UploadedDocumentSerializer(serializers.ModelSerializer[Document]):
    class Meta:
        model = Document
        fields = ("id", "title", "mime_type", "created", "added", "owner")
        read_only_fields = fields


class SavedViewSerializer(serializers.ModelSerializer[SavedView]):
    class Meta:
        model = SavedView
        fields = (
            "id",
            "name",
            "owner",
            "show_in_sidebar",
            "show_on_dashboard",
            "sort_field",
            "sort_reverse",
        )
        read_only_fields = ("id", "owner")


class PaperlessTaskSerializer(serializers.ModelSerializer[PaperlessTask]):
    class Meta:
        model = PaperlessTask
        fields = (
            "id",
            "task_id",
            "task_file_name",
            "task_status",
            "task_type",
            "task_return_value",
            "acknowledged",
            "status",
            "owner",
            "created",
        )
        read_only_fields = fields


class CustomFieldSerializer(serializers.ModelSerializer[CustomField]):
    class Meta:
        model = CustomField
        fields = (
            "id",
            "name",
            "slug",
            "data_type",
        )
        read_only_fields = fields

