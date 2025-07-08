from django.conf.urls import url
from rest_framework import routers
from juloserver.new_crm.views import (
    application_views,
    dropdown_views,
    streamlined_views
)

router = routers.DefaultRouter()

urlpatterns = [
    url(r'v1/app_status/(?P<application_id>[0-9]+)$', application_views.BasicAppDetail.as_view()),
    url(r'v1/app_status/detail/(?P<application_id>[0-9]+)$', application_views.AppDetail.as_view()),
    url(r'v1/app_status/status_change/(?P<application_id>[0-9]+)$', application_views.AppStatusChange.as_view()),
    url(r'v1/app_status/app_note/(?P<application_id>[0-9]+)$', application_views.AppNote.as_view()),
    url(r'v1/app_multi_image_upload/(?P<application_id>[0-9]+)$', application_views.AppMultiImageUpload.as_view()),
    url(r'v1/app_status/app_history/(?P<application_id>[0-9]+)$', application_views.AppStatusAppHistory.as_view()),
    url(r'v1/app_status/app_update_history/(?P<application_id>[0-9]+)$', application_views.AppDetailUpdateHistory.as_view()),
    url(r'v1/app_status/image_list/(?P<application_id>[0-9]+)$', application_views.AppStatusImageList.as_view()),
    url(r'v1/app_status/security/(?P<application_id>[0-9]+)$',application_views.AppSecurityTab.as_view()),
    url(r'v1/app_status/scrape_data/(?P<application_id>[0-9]+)$', application_views.AppScrapeDataView.as_view()),
    url(r'v1/app_status/skiptrace_history/(?P<application_id>[0-9]+)$', application_views.AppStatusSkiptraceHistory.as_view()),
    url(r'v1/app_status/email_sms_history/(?P<application_id>[0-9]+)$', application_views.EmailAndSmsHistory.as_view()),
    url(r'v1/app_status/finance/(?P<application_id>[0-9]+)$',application_views.AppFinanceView.as_view()),
    url(r'v1/app_status/skiptrace/(?P<application_id>[0-9]+)$', application_views.AppSkiptrace.as_view()),

    url(r'v1/app_status/bank', application_views.BankListView.as_view()),
    url(r'v1/dropdown/address/$', dropdown_views.DropdownAddressApi.as_view({'get': 'get'})),
    url(r'v1/dropdown/(?P<dropdown_type>[a-z]+)/$', dropdown_views.DropdownApi.as_view()),
    # Streamlined Communication URLS
    url(
        r'v1/streamlined/upload_user_data',
        streamlined_views.StreamlinedCommsImportUsersUploadFile.as_view(),
    ),
    url(
        r'v1/streamlined/segment_data_action/(?P<segment_id>[0-9]+)$',
        streamlined_views.StreamlinedCommsSegmentAction.as_view(),
    ),
    url(
        r'v1/streamlined/track_process_status/(?P<segment_id>[0-9]+)$',
        streamlined_views.StreamlinedCommsSegmentProcessStatus.as_view(),
    ),
    url(
        r'v1/streamlined/segment_error_details/(?P<segment_id>[0-9]+)$',
        streamlined_views.StreamlinedCommsSegmentErrorDetails.as_view(),
    ),
]
