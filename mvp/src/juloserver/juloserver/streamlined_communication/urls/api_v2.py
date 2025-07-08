from django.conf.urls import url
from rest_framework import routers
from .. import views

urlpatterns = [
    url(r'^android_ipa_banner$', views.IpaBannerAndroidAPIV2.as_view(), name='android_ipa_banner_v2'),
]
