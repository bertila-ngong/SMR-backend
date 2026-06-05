from datetime import datetime
from typing import Any

import magic
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from documents.models import Document
from documents.models import DocumentType
from documents.models import PaperlessTask
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


class PaperlessTaskSerializer(serializers.ModelSerializer):
    task_type_display = serializers.CharField(source="get_task_type_display", read_only=True)
    trigger_source_display = serializers.CharField(source="get_trigger_source_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    related_document_ids = serializers.SerializerMethodField()

    class Meta:
        model = PaperlessTask
        fields = (
            "id",
            "task_id",
            "task_type",
            "task_type_display",
            "trigger_source",
            "trigger_source_display",
            "status",
            "status_display",
            "date_created",
            "date_started",
            "date_done",
            "duration_seconds",
            "wait_time_seconds",
            "input_data",
            "result_data",
            "acknowledged",
            "related_document_ids",
        )
        read_only_fields = (
            "id", "task_id", "task_type", "task_type_display",
            "trigger_source", "trigger_source_display",
            "status", "status_display",
            "date_created", "date_started", "date_done",
            "duration_seconds", "wait_time_seconds",
            "input_data", "result_data", "related_document_ids",
        )

    def get_related_document_ids(self, obj) -> list[int]:
        doc_id = (obj.result_data or {}).get("document_id")
        return [doc_id] if doc_id else []


class DocumentSerializer(serializers.ModelSerializer):
    document_type = serializers.PrimaryKeyRelatedField(
        queryset=DocumentType.objects.all(), allow_null=True, required=False
    )
    content = serializers.SerializerMethodField()
    original_file_name = serializers.CharField(source="original_filename", read_only=True)
    download_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = (
            "id",
            "title",
            "content",
            "document_type",
            "created",
            "added",
            "modified",
            "mime_type",
            "original_file_name",
            "page_count",
            "archive_serial_number",
            "download_url",
            "thumbnail_url",
            "owner",
        )

    def get_content(self, obj) -> str | None:
        request = self.context.get("request")
        if request and request.query_params.get("truncate_content") == "true":
            return (obj.content or "")[:128] if obj.content else None
        return obj.content

    def get_download_url(self, obj) -> str:
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(f"/api/documents/{obj.pk}/download/")
        return f"/api/documents/{obj.pk}/download/"

    def get_thumbnail_url(self, obj) -> str:
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(f"/api/documents/{obj.pk}/thumb/")
        return f"/api/documents/{obj.pk}/thumb/"

