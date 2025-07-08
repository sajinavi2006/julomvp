from __future__ import unicode_literals

from django.conf.urls import url
from rest_framework import routers
from juloserver.partnership.liveness_partnership import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^settings', views.LivenessSettingsView.as_view(), name="liveness_settings"),
    url(
        r'^(?P<liveness_method>(passive|smile))/check$',
        views.LivenessCheckProcessView.as_view(),
        name="liveness_check_process",
    ),
]
