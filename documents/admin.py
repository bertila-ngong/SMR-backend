from django.contrib import admin

from documents.models import Document
from documents.models import DocumentType
from documents.models import StudentProfile
from documents.models import StudentRecord


@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "matching_algorithm")
    search_fields = ("name",)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "mime_type", "owner", "created", "added")
    list_filter = ("mime_type", "created", "added")
    search_fields = ("title", "original_filename", "content", "owner__username")
    readonly_fields = (
        "added",
        "modified",
        "mime_type",
        "checksum",
        "archive_checksum",
        "original_filename",
        "archive_filename",
        "filename",
        "deleted_at",
    )
    ordering = ("-id",)

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        return Document.global_objects.select_related("owner", "document_type")


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("matricule", "user", "date_of_birth", "password_change_required")
    search_fields = ("matricule", "user__username", "user__email")
    list_filter = ("password_change_required",)


@admin.register(StudentRecord)
class StudentRecordAdmin(admin.ModelAdmin):
    list_display = (
        "document",
        "student",
        "status",
        "needs_review",
        "submitted_at",
        "approved_at",
    )
    list_filter = ("status", "needs_review")
    search_fields = ("document__title", "student__username")
    readonly_fields = (
        "confidence",
        "raw_text",
        "extraction_source",
        "extraction_error",
        "extracted_at",
        "submitted_at",
        "reviewed_at",
        "approved_at",
        "reviewed_by",
    )
