import os
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from time import mktime
from typing import Any

import img2pdf
import magic
import pathvalidate
from django.conf import settings
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from pikepdf import Pdf
from rest_framework import parsers
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from documents.data_models import ConsumableDocument
from documents.data_models import DocumentMetadataOverrides
from documents.data_models import DocumentSource
from documents.models import Document
from documents.models import DocumentType
from documents.models import MatchingModel
from documents.models import PaperlessTask
from documents.models import StudentProfile
from documents.models import StudentRecord
from documents.parsers import is_mime_type_supported
from documents.permissions import get_objects_for_user_owner_aware
from documents.permissions import has_perms_owner_aware
from documents.serialisers import PostDocumentSerializer
from documents.serialisers import StudentRecordSerializer
from documents.student_notifications import send_pending_record_email
from documents.student_records import STUDENT_RECORD_DOCUMENT_TYPE
from documents.student_records import export_student_record_pdf
from documents.student_records import extract_student_record
from documents.student_records import get_or_create_student_record
from documents.student_records import student_record_needs_review
from documents.tasks import consume_file


class PostDocumentView(GenericAPIView[Any]):
    permission_classes = (IsAuthenticated,)
    serializer_class = PostDocumentSerializer
    parser_classes = (parsers.MultiPartParser,)

    def _validated_upload_part(self, name: str, data: bytes) -> tuple[str, bytes, str]:
        mime_type = magic.from_buffer(data, mime=True)
        if not is_mime_type_supported(mime_type):
            raise ValidationError(
                _("File type %(type)s not supported") % {"type": mime_type},
            )
        return name, data, mime_type

    def _combine_student_record_pages(
        self,
        files: list[tuple[str, bytes, str]],
    ) -> tuple[str, bytes]:
        if len(files) == 1:
            return files[0][0], files[0][1]

        merged_pdf = Pdf.new()
        for _name, data, mime_type in files:
            if mime_type == "application/pdf":
                source_pdf_bytes = data
            elif mime_type.startswith("image/"):
                source_pdf_bytes = img2pdf.convert(data)
            else:
                raise ValidationError(
                    _("File type %(type)s not supported") % {"type": mime_type},
                )

            with Pdf.open(BytesIO(source_pdf_bytes)) as source_pdf:
                merged_pdf.pages.extend(source_pdf.pages)

        output = BytesIO()
        merged_pdf.save(output)
        base_name = pathvalidate.sanitize_filename(Path(files[0][0]).stem)
        return f"{base_name}-student-record.pdf", output.getvalue()

    def post(self, request, *args, **kwargs):
        # Debug: Check user permissions
        import logging
        logger = logging.getLogger("paperless.views")
        logger.info(f"Document upload attempt by user: {request.user.username}")
        logger.info(f"User permissions: {list(request.user.user_permissions.values_list('codename', flat=True))}")
        logger.info(f"User has 'documents.add_document': {request.user.has_perm('documents.add_document')}")
        
        if not request.user.has_perm("documents.add_document"):
            logger.warning(f"User {request.user.username} denied document upload - insufficient permissions")
            return HttpResponseForbidden("Insufficient permissions")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        doc_name, doc_data = serializer.validated_data["document"]
        record_type = serializer.validated_data.get("record_type") or "student_record"
        student_matricule = serializer.validated_data.get("student_matricule")
        title = serializer.validated_data.get("title")
        created = serializer.validated_data.get("created")

        document_type, _ = DocumentType.objects.get_or_create(
            name=STUDENT_RECORD_DOCUMENT_TYPE,
            defaults={"matching_algorithm": MatchingModel.MATCH_NONE},
        )

        student_profile = getattr(request.user, "student_profile", None)
        if student_profile is None and student_matricule:
            student_profile = (
                StudentProfile.objects.select_related("user")
                .filter(matricule=student_matricule)
                .first()
            )
            if student_profile is None:
                raise ValidationError(_("No student exists with the provided matricule."))

        additional_documents = request.FILES.getlist("additional_documents")
        if record_type == "student_record" and len(additional_documents) > 2:
            raise ValidationError(
                _("Student records can contain at most three uploaded pages."),
            )

        files = [self._validated_upload_part(doc_name, doc_data)]
        for upload in additional_documents:
            files.append(self._validated_upload_part(upload.name, upload.file.read()))
        doc_name, doc_data = self._combine_student_record_pages(files)

        if student_profile is not None:
            student_record_name = pathvalidate.sanitize_filename(
                f"{student_profile.matricule}_studentrecord",
            )
            suffix = Path(doc_name).suffix or ".pdf"
            doc_name = f"{student_record_name}{suffix}"
            title = title or student_record_name

        timestamp = int(mktime(datetime.now().timetuple()))
        settings.SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
        temp_file_path = Path(tempfile.mkdtemp(dir=settings.SCRATCH_DIR)) / Path(
            pathvalidate.sanitize_filename(doc_name),
        )
        temp_file_path.write_bytes(doc_data)
        os.utime(temp_file_path, times=(timestamp, timestamp))

        input_doc = ConsumableDocument(
            source=DocumentSource.WebUI,
            original_file=temp_file_path,
        )
        overrides = DocumentMetadataOverrides(
            filename=doc_name,
            title=title,
            document_type_id=document_type.id,
            created=created,
            owner_id=student_profile.user_id if student_profile else request.user.id,
        )

        async_task = consume_file.apply_async(
            kwargs={"input_doc": input_doc, "overrides": overrides},
            headers={"trigger_source": PaperlessTask.TriggerSource.WEB_UI},
        )

        return Response({"task_id": async_task.id})


class StudentRecordView(GenericAPIView[Any]):
    permission_classes = (IsAuthenticated,)
    serializer_class = StudentRecordSerializer

    def is_student_user(self, user: User) -> bool:
        return hasattr(user, "student_profile")

    def is_admin_user(self, user: User) -> bool:
        return user.is_staff or user.is_superuser

    def get_document(self, document_id: int) -> Document:
        document = get_object_or_404(
            Document.objects.select_related("owner", "document_type"),
            pk=document_id,
        )
        if not has_perms_owner_aware(self.request.user, "view_document", document):
            raise PermissionDenied("Insufficient permissions")
        return document

    def get(self, request, document_id: int):
        document = self.get_document(document_id)
        record = get_or_create_student_record(document)
        return Response(self.get_serializer(record).data)

    def patch(self, request, document_id: int):
        document = self.get_document(document_id)
        if not has_perms_owner_aware(request.user, "change_document", document):
            raise PermissionDenied("Insufficient permissions")

        record = get_or_create_student_record(document)
        action = request.data.get("action")
        if action in {"approve", "changes_requested"} and not self.is_admin_user(
            request.user,
        ):
            raise PermissionDenied("Only administrators can review student records.")

        serializer_data = request.data.copy()
        serializer_data.pop("action", None)
        serializer = self.get_serializer(record, data=serializer_data, partial=True)
        serializer.is_valid(raise_exception=True)
        record = serializer.save()

        if action == "submit":
            record.status = StudentRecord.Status.PENDING
            record.needs_review = True
            record.submitted_at = timezone.now()
            record.reviewed_at = None
            record.approved_at = None
            record.reviewed_by = None
            record.student = record.student or (
                document.owner if self.is_student_user(document.owner) else None
            )
            record.save()
            send_pending_record_email(record)
        elif action == "approve":
            record.status = StudentRecord.Status.APPROVED
            record.needs_review = False
            record.reviewed_at = timezone.now()
            record.approved_at = timezone.now()
            record.reviewed_by = request.user
            record.save()
        elif action == "changes_requested":
            record.status = StudentRecord.Status.CHANGES_REQUESTED
            record.needs_review = True
            record.reviewed_at = timezone.now()
            record.approved_at = None
            record.reviewed_by = request.user
            record.save()
        elif self.is_student_user(request.user):
            record.status = StudentRecord.Status.DRAFT
            record.needs_review = False
            record.save(update_fields=["status", "needs_review"])
        elif "needs_review" in request.data:
            record.needs_review = request.data.get("needs_review", False)
            record.reviewed_at = timezone.now()
            record.reviewed_by = request.user
            record.save(update_fields=["needs_review", "reviewed_at", "reviewed_by"])

        return Response(self.get_serializer(record).data)

    def post(self, request, document_id: int):
        document = self.get_document(document_id)
        if not has_perms_owner_aware(request.user, "change_document", document):
            raise PermissionDenied("Insufficient permissions")

        record = get_or_create_student_record(document)
        extraction = extract_student_record(document)
        record.data = extraction.data
        record.confidence = extraction.confidence
        record.raw_text = extraction.raw_text
        record.extraction_source = extraction.source
        record.extraction_error = extraction.error
        record.needs_review = student_record_needs_review(
            extraction.data,
            extraction.confidence,
            extraction.error,
        )
        record.extracted_at = timezone.now()
        record.reviewed_at = None
        record.reviewed_by = None
        record.save()
        return Response(self.get_serializer(record).data)


class StudentRecordQueueView(GenericAPIView[Any]):
    permission_classes = (IsAuthenticated,)
    serializer_class = StudentRecordSerializer

    def get_queryset(self):
        queryset = StudentRecord.objects.select_related(
            "document",
            "student",
            "reviewed_by",
        ).order_by("-submitted_at", "-id")
        user = self.request.user
        if hasattr(user, "student_profile"):
            return queryset.filter(student=user) | queryset.filter(document__owner=user)
        if user.is_staff or user.is_superuser:
            return queryset
        documents = get_objects_for_user_owner_aware(user, "view_document", Document)
        return queryset.filter(document__in=documents)

    def get(self, request):
        queryset = self.get_queryset()
        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return Response(self.get_serializer(queryset[:100], many=True).data)


class StudentRecordPdfView(StudentRecordView):
    def get(self, request, document_id: int):
        document = self.get_document(document_id)
        record = get_or_create_student_record(document)
        pdf_bytes = export_student_record_pdf(record)
        filename = pathvalidate.sanitize_filename(
            f"{document.title or f'document-{document.id}'}-student-record.pdf",
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
