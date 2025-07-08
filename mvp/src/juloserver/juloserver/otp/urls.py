from django.conf.urls import url
from rest_framework import routers

from juloserver.otp.views import (
    MisCallCallBackResult,
    OTPCheckAllowed,
    OtpExpire,
    OtpRequest,
    OtpRequestV2,
    OtpValidation,
    OtpValidationV2,
    OTPVerificationPage,
    OTPWebVerification,
    OtpExperimentCheck,
    InitialServiceTypeCheck,
)

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^v1/check-user-allowed$', OTPCheckAllowed.as_view()),
    url(r'^v1/request$', OtpRequest.as_view()),
    url(r'^v1/validate$', OtpValidation.as_view()),
    url(r'^v2/request$', OtpRequestV2.as_view()),
    url(r'^v2/validate$', OtpValidationV2.as_view()),
    url(r'^v1/session-token/expire$', OtpExpire.as_view()),
    url(r'^v1/miscall-callback/(?P<callback_id>[A-Za-z0-9]+)$', MisCallCallBackResult.as_view()),
    url(
        r'^v1/verification/(?P<otp_type>.+)/(?P<customer_xid>.+)/$',
        OTPVerificationPage.as_view(),
        name="get-otp-verification",
    ),
    url(r'^v1/verification/(?P<customer_xid>.+)/$', OTPWebVerification.as_view()),
    url(r'^v2/otp-experiment$', OtpExperimentCheck.as_view()),
    url(r'^v1/initial-service-type$', InitialServiceTypeCheck.as_view()),
]
