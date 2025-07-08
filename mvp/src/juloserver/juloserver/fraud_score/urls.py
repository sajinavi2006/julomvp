from __future__ import unicode_literals

from django.conf.urls import include, url
from rest_framework import routers

from juloserver.fraud_score.views import (
    TrustGuardScoreView,
    JuicyScoreView,
    TrustGuardBlackBoxView,
)

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^trust_guard/score', TrustGuardScoreView.as_view(), name='trust_guard_score'),
    url(r'^trust_guard/blackbox', TrustGuardBlackBoxView.as_view(), name='trust_guard_blackbox'),
    url(r'^juicy_score/score', JuicyScoreView.as_view(), name='juicy_score'),
]
