from django.conf.urls import url
from rest_framework import routers

from juloserver.ocr.views.views_api_v4 import KTPOCRResultView

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^ktp/$', KTPOCRResultView.as_view()),
]
