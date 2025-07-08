from django.conf.urls import url
from rest_framework import routers
from .. import views
from juloserver.streamlined_communication.views import (
    CampaignCreateListView,
    CampaignDropdownListView,
    CampaignTestSmsView,
    DownloadCampaignReportView,
    ApproveRejectCommsCampaignView,
    CampaignDetailView,
    UserDetailsView,
)
router = routers.DefaultRouter()

urlpatterns = [
    url(r'^list/$', views.streamlined_communication, name='list'),
    url(r'^download_call_record/$', views.download_call_record, name='download_call_record'),
    url(r'^update_sms_details', views.update_sms_details, name='update_sms_details'),
    url(r'^update_robocall_details', views.update_robocall_details, name='update_robocall_details'),
    url(r'^update_pn_details', views.update_pn_details, name='update_pn_details'),
    url(r'^update_email_details', views.update_email_details, name='update_email_details'),
    url(
        r'^update_parameterlist_details',
        views.update_parameterlist_details,
        name='update_parameterlist_details',
    ),
    url(
        r'^create_update_widget_due_date',
        views.create_update_widget_due_date,
        name='create_update_widget_due_date',
    ),
    url(
        r'^create_update_slik_notification',
        views.create_update_slik_notification,
        name='create_update_slik_notification',
    ),
    url(r'^nexmo_robocall_test', views.nexmo_robocall_test, name='nexmo_robocall_test'),
    url(r'^get_info_card_property', views.get_info_card_property,
        name='get_info_card_property'),
    url(r'^create_new_info_card', views.CreateNewInfoCard.as_view(), name='create_new_info_card'),
    url(r'^update_info_card', views.UpdateInfoCard.as_view(), name='update_info_card'),
    url(r'^info_card_update_ordering_and_activate',
        views.info_card_update_ordering_and_activate,
        name='info_card_update_ordering_and_activate'),
    url(r'^delete_info_card', views.delete_info_card, name='delete_info_card'),
    url(r'^get_pause_reminder', views.get_pause_reminder, name='get_pause_reminder'),
    url(r'^submit_pause_reminder', views.submit_pause_reminder, name='submit_pause_reminder'),
    url(r'^mocking_sms_text_value', views.mocking_sms_text_value, name='mocking_sms_text_value'),
    url(r'^campaign/$', CampaignCreateListView.as_view(), name='campaign_create_list'),
    url(
        r'^campaign/get_dropdown_list$',
        CampaignDropdownListView.as_view(),
        name='campaign_drop_down_list',
    ),
    url(r'^campaign/test_sms', CampaignTestSmsView.as_view(), name='test_sms'),
    url(
        r'^campaign/download-report',
        DownloadCampaignReportView.as_view(),
        name='download_report_campaign',
    ),
    url(
        r'^campaign/approve_reject',
        ApproveRejectCommsCampaignView.as_view(),
        name='approve_reject_comms_campaign',
    ),
    url(r'^campaign/(?P<campaign_id>\d+)/$', CampaignDetailView.as_view(), name='campaign_detail'),
    url(r'^get_user_details', UserDetailsView.as_view(), name='get_user_details'),
]
