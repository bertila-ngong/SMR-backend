from django.urls import re_path

from documents.views import PostDocumentView
from documents.views import StudentRecordPdfView
from documents.views import StudentRecordQueueView
from documents.views import StudentRecordView

api_urlpatterns = [
    re_path(
        "^documents/post_document/$",
        PostDocumentView.as_view(),
        name="post_document",
    ),
    re_path(
        r"^student_records/$",
        StudentRecordQueueView.as_view(),
        name="student_record_queue",
    ),
    re_path(
        r"^student_records/(?P<document_id>\d+)/$",
        StudentRecordView.as_view(),
        name="student_record",
    ),
    re_path(
        r"^student_records/(?P<document_id>\d+)/pdf/$",
        StudentRecordPdfView.as_view(),
        name="student_record_pdf",
    ),
]

public_urlpatterns = []

urlpatterns = api_urlpatterns
