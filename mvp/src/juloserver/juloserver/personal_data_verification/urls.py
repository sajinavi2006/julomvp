from __future__ import unicode_literals

from django.conf.urls import include, url
from rest_framework import routers

from juloserver.personal_data_verification.views import BureauSessionCreation

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(
        r'^bureau-sdk-session',
        BureauSessionCreation.as_view(),
        name='bureau-sdk-session'),
]
