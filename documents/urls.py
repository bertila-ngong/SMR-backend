from django.conf import settings
from django.conf.urls import include
from django.urls import path
from django.urls import re_path
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter

from documents.views import BulkDownloadView
from documents.views import BulkEditObjectsView
from documents.views import BulkEditView
from documents.views import ChatStreamingView
from documents.views import CorrespondentViewSet
from documents.views import CustomFieldViewSet
from documents.views import DeleteDocumentsView
from documents.views import DocumentTypeViewSet
from documents.views import EditPdfDocumentsView
from documents.views import GlobalSearchView
from documents.views import LogViewSet
from documents.views import MergeDocumentsView
from documents.views import PostDocumentView
from documents.views import RemoteVersionView
from documents.views import RemovePasswordDocumentsView
from documents.views import ReprocessDocumentsView
from documents.views import RotateDocumentsView
from documents.views import SavedViewViewSet
from documents.views import SearchAutoCompleteView
from documents.views import SelectionDataView
from documents.views import SharedLinkView
from documents.views import ShareLinkBundleViewSet
from documents.views import ShareLinkViewSet
from documents.views import StatisticsView
from documents.views import StoragePathViewSet
from documents.views import StudentRecordView
from documents.views import SystemStatusView
from documents.views import TagViewSet
from documents.views import TasksViewSet
from documents.views import TrashView
from documents.views import UiSettingsView
from documents.views import UnifiedSearchViewSet
from documents.views import WorkflowActionViewSet
from documents.views import WorkflowTriggerViewSet
from documents.views import WorkflowViewSet
from documents.views import serve_logo

router = DefaultRouter()
router.register(r"correspondents", CorrespondentViewSet)
router.register(r"document_types", DocumentTypeViewSet)
router.register(r"documents", UnifiedSearchViewSet)
router.register(r"logs", LogViewSet, basename="logs")
router.register(r"tags", TagViewSet)
router.register(r"saved_views", SavedViewViewSet)
router.register(r"storage_paths", StoragePathViewSet)
router.register(r"tasks", TasksViewSet, basename="tasks")
router.register(r"share_link_bundles", ShareLinkBundleViewSet)
router.register(r"share_links", ShareLinkViewSet)
router.register(r"workflow_triggers", WorkflowTriggerViewSet)
router.register(r"workflow_actions", WorkflowActionViewSet)
router.register(r"workflows", WorkflowViewSet)
router.register(r"custom_fields", CustomFieldViewSet)

api_urlpatterns = [
    re_path(
        "^search/",
        include(
            [
                re_path("^$", GlobalSearchView.as_view(), name="global_search"),
                re_path(
                    "^autocomplete/",
                    SearchAutoCompleteView.as_view(),
                    name="autocomplete",
                ),
            ],
        ),
    ),
    re_path("^statistics/", StatisticsView.as_view(), name="statistics"),
    re_path(
        "^documents/",
        include(
            [
                re_path(
                    "^post_document/",
                    PostDocumentView.as_view(),
                    name="post_document",
                ),
                re_path("^bulk_edit/", BulkEditView.as_view(), name="bulk_edit"),
                re_path(
                    "^delete/",
                    DeleteDocumentsView.as_view(),
                    name="delete_documents",
                ),
                re_path(
                    "^reprocess/",
                    ReprocessDocumentsView.as_view(),
                    name="reprocess_documents",
                ),
                re_path(
                    "^rotate/",
                    RotateDocumentsView.as_view(),
                    name="rotate_documents",
                ),
                re_path("^merge/", MergeDocumentsView.as_view(), name="merge_documents"),
                re_path(
                    "^edit_pdf/",
                    EditPdfDocumentsView.as_view(),
                    name="edit_pdf_documents",
                ),
                re_path(
                    "^remove_password/",
                    RemovePasswordDocumentsView.as_view(),
                    name="remove_password_documents",
                ),
                re_path(
                    "^bulk_download/",
                    BulkDownloadView.as_view(),
                    name="bulk_download",
                ),
                re_path(
                    "^selection_data/",
                    SelectionDataView.as_view(),
                    name="selection_data",
                ),
                re_path(
                    "^chat/",
                    ChatStreamingView.as_view(),
                    name="chat_streaming_view",
                ),
            ],
        ),
    ),
    re_path(
        "^bulk_edit_objects/",
        BulkEditObjectsView.as_view(),
        name="bulk_edit_objects",
    ),
    re_path("^remote_version/", RemoteVersionView.as_view(), name="remoteversion"),
    re_path("^ui_settings/", UiSettingsView.as_view(), name="ui_settings"),
    re_path("^status/", SystemStatusView.as_view(), name="system_status"),
    re_path(
        r"^student_records/(?P<document_id>\d+)/$",
        StudentRecordView.as_view(),
        name="student_record",
    ),
    re_path("^trash/", TrashView.as_view(), name="trash"),
    *router.urls,
]

public_urlpatterns = [
    re_path(r"share/(?P<slug>\w+)/?$", SharedLinkView.as_view()),
    re_path(
        r"^fetch/",
        include(
            [
                re_path(
                    r"^doc/(?P<pk>\d+)$",
                    RedirectView.as_view(
                        url=settings.BASE_URL + "api/documents/%(pk)s/download/",
                    ),
                ),
                re_path(
                    r"^thumb/(?P<pk>\d+)$",
                    RedirectView.as_view(
                        url=settings.BASE_URL + "api/documents/%(pk)s/thumb/",
                    ),
                ),
                re_path(
                    r"^preview/(?P<pk>\d+)$",
                    RedirectView.as_view(
                        url=settings.BASE_URL + "api/documents/%(pk)s/preview/",
                    ),
                ),
            ],
        ),
    ),
    path(
        "assets/<path:path>",
        RedirectView.as_view(
            url=settings.STATIC_URL + "frontend/en-US/assets/%(path)s",
        ),
    ),
    re_path(r"^logo(?:/(?P<filename>.+))?/?$", serve_logo, name="app_logo"),
]

urlpatterns = api_urlpatterns + public_urlpatterns
