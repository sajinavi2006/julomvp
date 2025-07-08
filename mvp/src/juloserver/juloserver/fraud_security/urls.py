from __future__ import unicode_literals

from django.conf.urls import include, url
from rest_framework import routers

from juloserver.fraud_security import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^security', views.fraud_security_page_view, name="security"),
    url(r'^geohash/list', views.GeohashCRMView.as_view(), name="geohash-list"),
    url(r'^geohash/app-list', views.GeohashApplicationView.as_view(), name="geohash-app-list"),
    url(
        r'^app_status/(?P<bucket_type>[a-z_-]+)/list',
        views.FraudApplicationList.as_view(),
        name="app-bucket-list",
    ),
    url(r'^device-identity', views.DeviceIdentityView.as_view(), name="device-identity"),
    url(r'^fraud-block-account', views.FraudBlockAccountView.as_view(), name="fraud-block-account"),
]
