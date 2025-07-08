from django.conf.urls import url
from rest_framework import routers

from juloserver.liveness_detection.views import (
    ActiveLivenessCheck,
    ActiveLivenessCheckV2,
    ActiveLivenessSequence,
    AndroidAppLicense,
    PreCheck,
    SmileLivenessCheck,
    PreCheckV2,
    PreSmileLivenessCheck,
    ActiveSmileCheck,
    PreCheckV3,
    LivenessCheck,
    IOSAppLicense,
)

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^v1/active-check$', ActiveLivenessCheck.as_view()),
    url(r'^v2/active-check$', ActiveLivenessCheckV2.as_view()),
    url(r'^v1/pre-active-check$', ActiveLivenessSequence.as_view()),
    url(r'^v1/pre-check$', PreCheck.as_view()),
    url(r'^v1/license$', AndroidAppLicense.as_view()),
    url(r'^v2/pre-check$', PreCheckV2.as_view()),
    url(r'^v1/pre-smile-check$', PreSmileLivenessCheck.as_view()),
    url(r'^v1/smile-check$', SmileLivenessCheck.as_view()),
    url(r'^v1/smile-active-check$', ActiveSmileCheck.as_view()),
    url(r'^v3/pre-check$', PreCheckV3.as_view()),
    url(r'^v1/liveness-check$', LivenessCheck.as_view()),
    url(r'^v1/license/ios$', IOSAppLicense.as_view(), name='ios-license'),
]
