from django.conf.urls import url
from rest_framework import routers
from juloserver.streamlined_communication import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^infobip-sms-report', views.InfobipSmsReport.as_view(), name='infobip_sms_callback'),
    url(r'^infobip-voice-report', views.InfobipVoiceReport.as_view(), name='infobip_voice_callback'),
    url(r'^alicloud-sms-report', views.AlicloudSmsReport.as_view(), name='alicloud_sms_callback'),
    url(
        r'^otpless-delivery-report',
        views.OTPLessDeliveryReport.as_view(),
        name='otpless_delivery_report',
    ),
    url(
        r'^otpless-verification-report',
        views.OTPLessVerificationReport.as_view(),
        name='otpless_verification_report',
    ),
    url(
        r'^otpless-sms-callback',
        views.OTPLessSMSCallbackEntryPoint.as_view(),
        name='otpless_sms_callback',
    ),
    url(
        r'^outbound-call-callback',
        views.CommunicationServiceOutboundCallView.as_view(),
        name='communication_service_outbound_call_callback',
    ),
]
