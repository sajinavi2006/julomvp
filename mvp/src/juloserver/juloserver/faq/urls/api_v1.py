from __future__ import unicode_literals
from __future__ import absolute_import

from rest_framework import routers
from django.conf.urls import url

from juloserver.faq.views.views_api_v1 import (
    FaqAPIView,
)


router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^questions/(?P<feature_name>[A-Za-z0-9]+)$',
        FaqAPIView.as_view(),
        name='faq_v1'
    ),
]
