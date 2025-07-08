from __future__ import unicode_literals

from django.conf.urls import include, url
from rest_framework import routers

from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^v1/check-expire-early', views.CheckExpireEarly.as_view()),
    url(r'^v1/token/refresh$', views.RetrieveNewAccessToken.as_view()),
    url(r'^v1/device-verification$', views.DeviceVerification.as_view(), name="device-verification")

]
