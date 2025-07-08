from __future__ import unicode_literals
from django.conf.urls import url
from rest_framework import routers
from juloserver.julo_starter.views import view_v2

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^application/(?P<pk>[0-9]+)$', view_v2.ApplicationUpdateV2.as_view()),
    url(
        r'^user-check-eligibility/(?P<customer_id>[0-9]+)$',
        view_v2.UserCheckEligibility.as_view(),
    ),
    url(
        r'^check-process-eligibility/(?P<customer_id>[0-9]+)$',
        view_v2.CheckProcessEligibility.as_view(),
    ),
]
