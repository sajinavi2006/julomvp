from django.conf.urls import url
from rest_framework import routers

from juloserver.historical.views import BioSensorHistory, PreBioSensorHistory

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^v1/bio-sensor-histories$', BioSensorHistory.as_view()),
    url(r'^v1/pre-bio-sensor-histories$', PreBioSensorHistory.as_view())
]
