from __future__ import unicode_literals

from django.conf.urls import include, url

from rest_framework import routers

from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^upload_intelix_call_results/', views.IntelixUploadCallResults.as_view()),
    url(r'^upload/update-intelix-skiptrace-data-agent-level-calls',
        views.UpdateIntelixSkiptraceDataAgentLevel.as_view()),
    url(r'^store_recording_file_and_detail/', views.StoringCallRecordingDetail.as_view()),
    url(r'^store_in_app_ptp/', views.InAppPtp.as_view()),
    url(r'^set_callback_promise_time/', views.CallbackPromiseSetSlotTime.as_view()),
    url(r'^genesys_manual_upload_call_results/', views.GenesysManualUploadCallResults.as_view()),
    url(
        r'^set_blacklist_account/',
        views.IntelixBlackListAccount.as_view(),
        name='set_blacklist_account',
    ),
    url(r'^blacklist/', views.blacklist_dialer_account, name='blacklist'),
    url(
        r'^collection_download_manual_upload_intelix_csv/',
        views.collection_download_manual_upload_intelix_csv,
        name='collection_download_manual_upload_intelix_csv',
    ),
    url(r'^delete_phone_number/', views.delete_phone_number, name='delete_phone_number'),
    url(
        r'^process_bulk_download_manual_upload_intelix_csv_files_trigger',
        views.process_bulk_download_manual_upload_intelix_csv_files_trigger,
        name='process_bulk_download_manual_upload_intelix_csv_files_trigger',
    ),
    url(
        r'^taks_progress/(?P<task_id>[\w-]+)/$',
        views.get_bulk_download_manual_upload_intelix_csv_files_progress,
        name='get_bulk_download_manual_upload_intelix_csv_files_progress',
    ),
    url(r'^airudder/webhooks', views.AiRudderWebhooks.as_view()),
    url(r'^bulk_cancel_call_ai_rudder',
        views.page_bulk_cancel_call_from_ai_rudder, name='bulk_cancel_call_ai_rudder'),
    url(r'^airudder/task_configuration',
        views.page_ai_rudder_task_configuration, name='ai_rudder_task_configuration'),
    url(r'^airudder/ai_rudder_task_configuration_api',
        views.ai_rudder_task_configuration_api, name='ai_rudder_task_configuration_api'),
    url(r'^grab/airudder/webhooks', views.GrabAiRudderWebhooks.as_view()),
    url(r'^bulk_change_user_role',
        views.page_bulk_change_user_role, name='page_bulk_change_user_role'),
    url(r'^airudder/risk-webhooks', views.BucketRiskAiRudderWebhooks.as_view()),
    url(r'^field-coll/account/detail/(?P<account_id>[0-9]+)', views.GetAccountDetail.as_view()),
    url(r'^field-coll/skiptrace/update', views.UpdateFCSkiptrace.as_view()),
    url(r'^dataplatform/b5-webhooks', views.Bucket5DataGenerationTrigger.as_view()),
    url(r'^dataplatform/b6-webhooks', views.Bucket6DataGenerationTrigger.as_view()),
    url(
        r'^field-coll/datapopulation/webhooks/(?P<bucket_type>b2|b3|b5)',
        views.FieldCollDataPopulationTrigger.as_view(),
    ),
    url(
        r'^dataplatform/bucket-current-webhooks', views.TriggerDataGenerationCurrentBucket.as_view()
    ),
    url(r'^dataplatform/bucket-1-webhooks', views.TriggerProcessBTTCBucket1.as_view()),
    url(
        r'^field-coll/account/(?P<account_id>[0-9]+)/account-payment/$',
        views.FCAccountPaymentList.as_view(),
    ),
]
