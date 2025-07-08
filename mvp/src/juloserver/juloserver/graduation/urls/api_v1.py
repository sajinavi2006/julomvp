from __future__ import unicode_literals
from django.conf.urls import url
from rest_framework import routers

from juloserver.graduation.views import views_api_v1

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^downgrade-info-alert', views_api_v1.DowngradeInfoAlertAPIView.as_view()),
]
