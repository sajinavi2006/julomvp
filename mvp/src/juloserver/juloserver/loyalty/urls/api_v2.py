from __future__ import unicode_literals
from __future__ import absolute_import

from rest_framework import routers
from django.conf.urls import url

from juloserver.loyalty.views.views_api_v2 import (
    PointInformationAPIViewV2,
    LoyaltyInfoAPIViewV2,
    LoyaltyMissionDetailAPIViewV2,
)


router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^point-information',
        PointInformationAPIViewV2.as_view(),
        name='point_information_v2'
    ),
    url(
        r'^info$',
        LoyaltyInfoAPIViewV2.as_view(),
        name='info_v2'
    ),
    url(
        r'^mission/details/(?P<mission_config_id>[0-9]+)$',
        LoyaltyMissionDetailAPIViewV2.as_view(),
        name='mission_detail_v2'
    ),
]
