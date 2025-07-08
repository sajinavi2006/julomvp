from __future__ import unicode_literals
from django.conf.urls import url
from rest_framework import routers
from juloserver.apiv4.views import api_views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^tnc-and-privacynotice', api_views.TermsConditionAndPrivacyNotice.as_view()),
    url(r'^application/(?P<pk>[0-9]+)/$', api_views.ApplicationUpdateV4.as_view()),
    url(r'^etl/dsd/$', api_views.DeviceScrapedDataUploadV4.as_view()),
]
