from django.conf.urls import include, url
from rest_framework import routers

from juloserver.ocr.views.views_api_v2 import (
    GetOCROpenCVSetting,
    KTPOCRResultView2,
    SaveKTPtoApplicationDocument,
)

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^ktp/$', KTPOCRResultView2.as_view()),
    url(r'^ktp/submit/$', SaveKTPtoApplicationDocument.as_view()),
    url(r'^setting/ocr_timeout$', GetOCROpenCVSetting.as_view()),
]
