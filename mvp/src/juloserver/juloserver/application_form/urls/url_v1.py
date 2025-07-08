from django.conf.urls import url
from rest_framework import routers

from juloserver.application_form.views import view_v1 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^application/(?P<pk>[0-9]+)$', views.ApplicationUpdate.as_view()),
    url(r'^regions/check', views.RegionCheck.as_view()),
    url(r'^precheck-reapply', views.ApplicationPrecheckReapply.as_view()),
    url(r'^reapply', views.ApplicationReapply.as_view()),
    url(r'^cancel', views.ApplicationCancelation.as_view()),
    url(r'^product-picker', views.ApplicationProductPicker.as_view()),
    url(r'^application-upgrade', views.ApplicationUpgrade.as_view()),
    url(r'^create-profile', views.CreateProfileRequest.as_view()),
    url(r'^idfy/video/callback$', views.ApplicationCallbackFromIDFy.as_view()),
    url(r'^video/result/(?P<application_id>[0-9]+)$', views.ApplicationResultFromIDFy.as_view()),
    url(r'^video/entry-page$', views.IdfyInstructionPage.as_view()),
    url(r'^idfy/video/callback/session-drop-off', views.IDFySessionWebhookView.as_view()),
    url(r'^app-destination-page$', views.ApplicationDestinationPage.as_view()),
    url(r'^bottomsheet-contents$', views.BottomSheetContents.as_view()),
    url(r'^application/apply$', views.ApplicationFormMTL.as_view()),
    url(r'^application/emergency-contacts', views.EmergencyContactForm.as_view()),
    url(r'^emergency-contacts/consent$', views.EmergencyContactConsentForm.as_view()),
    url(r'^application/ocr_result/(?P<application_id>[0-9]+)$', views.RetrieveOCRResult.as_view()),
    url(
        r'^application/confirm-ktp/(?P<application_id>[0-9]+)$', views.ConfirmCustomerNIK.as_view()
    ),
    url(r'^video/availability$', views.VideoCallAvailabilityView.as_view()),
    url(
        r'^application/(?P<pk>[0-9]+)/assisted-submission$',
        views.AgentAssistedApplicationUpdate.as_view(),
    ),
    url(
        r'^sales-ops-assistance/tnc$',
        views.SalesOpsTermsAndConditionView.as_view(),
    ),
    url(r'^application/phone-number/submit$', views.ApplicationPhoneNumberSubmitView.as_view()),
    url(
        r'^mother-maiden-name/setting/(?P<application_id>[0-9]+)$',
        views.MotherMaidenNameSettingView.as_view(),
    ),
]
