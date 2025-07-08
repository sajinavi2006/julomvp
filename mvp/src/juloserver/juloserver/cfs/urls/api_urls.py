from django.conf.urls import url
from rest_framework import routers

from ..views import api_views, api_v2_views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^v1/get_faqs$', api_views.GetCfsFAQs.as_view()),
    url(r'^v1/get_status/(?P<application_id>[0-9]+)$', api_views.GetCfsStatus.as_view()),
    url(r'^v1/get_missions/(?P<application_id>[0-9]+)$', api_views.GetCfsMissions.as_view()),
    url(r'^v1/claim_rewards/(?P<application_id>[0-9]+)$', api_views.ClaimCfsRewards.as_view()),
    url(r'^v1/do_mission/upload_document/(?P<application_id>[0-9]+)$',
        api_views.CfsAssignmentActionUpLoadDocument.as_view()),
    url(r'^v1/do_mission/verify_address/(?P<application_id>[0-9]+)$',
        api_views.CfsAssignmentActionVerifyAddress.as_view()),
    url(r'^v1/do_mission/connect_bank/(?P<application_id>[0-9]+)$',
        api_views.CfsAssignmentActionConnectBank.as_view()),
    url(r'^v1/do_mission/connect_bpjs/(?P<application_id>[0-9]+)$',
        api_views.CfsAssignmentActionConnectBPJS.as_view()),
    url(r'^v1/do_mission/add_related_phone/(?P<application_id>[0-9]+)$',
        api_views.CfsAssignmentActionAddRelatedPhone.as_view()),
    url(r'^v1/do_mission/share_social_media/(?P<application_id>[0-9]+)$',
        api_views.CfsAssignmentActionShareSocialMedia.as_view()),
    url(r'^v1/do_mission/verify_phone_number_1/(?P<application_id>[0-9]+)$',
        api_views.CfsAssignmentActionVerifyPhoneNumber1.as_view()),
    url(r'^v1/do_mission/verify_phone_number_2/(?P<application_id>[0-9]+)$',
        api_views.CfsAssignmentActionVerifyPhoneNumber2.as_view()),
    url(r'^v1/validate/notification$',
        api_views.CfsAndroidCheckNotificationValidity.as_view()),
    url(r'^v1/get_tiers$', api_views.CfsGetTiers.as_view()),
    url(r'^v1/get_customer_j_score_histories$', api_views.CustomerJScoreHistories.as_view()),
    url(r'^v1/get_customer_j_score_history_details$',
        api_views.CustomerJScoreHistoryDetails.as_view()),
    url(r'^v1/get_page_accessibility$', api_views.PageAccessibility.as_view()),

    url(r'^v1/mission_web_url$', api_views.MissionWebUrlView.as_view()),
    url(r'^v1/easy_income_info$', api_views.EasyIncomeView.as_view()),
    url(r'^v1/perfios_page_url$', api_views.PerfiosPageURLListView.as_view()),

   # v2
    url(r'^v2/do_mission/verify_phone_number_2/(?P<application_id>[0-9]+)$',
        api_v2_views.CfsAssignmentActionVerifyPhoneNumber2.as_view()),
    url(r'^v2/web/images/$', api_v2_views.CFSWebImageCreateView.as_view()),
    url(r'^v2/web/do_mission/upload_document/$',
        api_v2_views.CFSWebAssignmentActionUpLoadDocument.as_view()),
]
