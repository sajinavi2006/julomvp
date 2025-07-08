from django.conf.urls import include, url
from rest_framework import routers

from ..views.views_api_v1 import (
    KTPOCRResultView,
    KTPOCRExperimentStoredView,
)

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^ktp/$', KTPOCRResultView.as_view()),
    url(r'^experiment/ktp$', KTPOCRExperimentStoredView.as_view()),
]
