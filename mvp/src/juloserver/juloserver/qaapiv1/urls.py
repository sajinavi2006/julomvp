from __future__ import unicode_literals

from django.conf.urls import include, url
from rest_framework import routers

from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^update_payment/', views.RunUpdatePayment.as_view()),
    url(r'^change_application_history/cdate/', views.ChangeAppHistoryCdate.as_view()),
    url(r'^reminder/submit_doc_am/', views.SubmitDocReminderAm.as_view()),
    url(r'^reminder/submit_doc_pm/', views.SubmitDocReminderPm.as_view()),
    url(r'^reminder/resubmit_doc_am/', views.ResubmitDocReminderAm.as_view()),
    url(r'^reminder/resubmit_doc_pm/', views.ResubmitDocReminderPm.as_view()),
    url(r'^reminder/pv_am/', views.PhoneVerificationReminderAm.as_view()),
    url(r'^reminder/pv_pm/', views.PhoneVerificationReminderPm.as_view()),
    url(r'^reminder/accept_offer_am/', views.AcceptOfferReminderAm.as_view()),
    url(r'^reminder/accept_offer_pm/', views.AcceptOfferReminderPm.as_view()),
    url(r'^reminder/sign_sphp_am/', views.SignSphpReminderAm.as_view()),
    url(r'^reminder/sign_sphp_pm/', views.SignSphpReminderPm.as_view()),
    url(r'^sendgcm/', views.SendGcm.as_view()),
    url(r'^scheduledtasks/(?P<scheduled_task>.+)$', views.ScheduledTaskTriggerView.as_view()),
    url(r'^google/auth/redirection$', views.GmailAuthRedirectionView.as_view()),
    url(r'^google/auth/callback$', views.GmailAuthCallbackView.as_view()),
    url(r'^customer/set_email_verified$', views.SetEmailVerified.as_view()),
    url(r'^change_customer/cdate/', views.ChangeCustomerCdate.as_view()),
    url(r'^accountchanger/?$', views.AccountChanger.as_view()),
    url(r'^loctask/execute_loc_notification/?$', views.ExecuteLocNotificationTask.as_view()),
    url(r'^randomize/imei_and_android_id?$', views.RandomizeImeiAndAndroidId.as_view()),
    url(r'^modify/credit_score?$', views.ModifyCreditScore.as_view()),
    url(r'^bca/generate_signature?$', views.GenerateBcaSignature.as_view()),
    url(r'^bug_champion/login?$', views.BugChampionLoginView.as_view()),
    url(r'^bug_champion/change_status?$', views.BugChampionForceChangeStatusView.as_view()),
    url(r'^bug_champion/rescrape?$', views.BugChampionRescrapeActionView.as_view()),
    url(r'^bug_champion/payment_method?$', views.BugChampionDisbursementMethodView.as_view()),
    # url(r'^bug_champion/delete_payment_event?$',
    #     views.BugChampionPaymentEventView.as_view()),
    # url(r'^bug_champion/activate_loan_for_manual_disburse?$',
    #     views.BugChampionActivateLoanManualDisburseView.as_view()),
    # url(r'^bug_champion/payment_agent_reassignment?$',
    #     views.BugChampionPaymentAgentReassignment.as_view()),
    url(r'^bug_champion/validate_customer_bank?$', views.BugChampionValidateCustomerBank.as_view()),
    # url(r'^bug_champion/unlock?$',
    #     views.BugChampionUnlock.as_view()),
    url(r'^bug_champion/waive_refinancing?$', views.BugChampionWaiveRefinance.as_view()),
    url(r'^bug_champion/create_dvc?$', views.BugChampionCreateDVC.as_view()),
    url(r'^bug_champion/payment_discount?$', views.BugChampionPaymentDiscount.as_view()),
    url(r'^faspay/generate_signature/(?P<va>[0-9]+)/?$', views.GenerateFaspaySignature.as_view()),
    url(
        r'^faspay/generate_signature/notification?$',
        views.GenerateFaspayPaymentNotificationSignature.as_view(),
    ),
    url(r'^bug_champion/change_name?$', views.BugChampionChangeNameKtp.as_view()),
    url(r'^bug_champion/payment_restructure?$', views.BugChampionPaymentRestructure.as_view()),
    url(r'^manual_disburse', views.ManualDisburseFakeCallBack.as_view()),
    # change application status
    url(
        r'^change_application_status/(?P<application_id>[0-9]+)/$',
        views.ChangeApplicationStatus.as_view(),
    ),
]
