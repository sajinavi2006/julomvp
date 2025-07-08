from __future__ import unicode_literals
from django.conf.urls import url
from rest_framework import routers
from juloserver.julo_savings.views import api_views

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^whitelist-status/(?P<application_id>[0-9]+)$',
        api_views.GetWhitelistStatus.as_view(),
    ),
    url(
        r'^blu/welcome',
        api_views.GetBenefitWelcomeContent.as_view(),
    ),
]
