from django.conf.urls import url
from rest_framework import routers

from ..views.views_api_v3 import KTPOCRResultView3

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^ktp/$', KTPOCRResultView3.as_view()),
]
