from __future__ import unicode_literals

from django.conf.urls import include, url
from rest_framework import routers

from juloserver.fraud_report import views

router = routers.DefaultRouter()

urlpatterns = [
     url(r'^', include(router.urls)),
     url(r'^submit_report', views.FraudReportSubmitView.as_view()),
     url(r'^download_fraud_report/(?P<application_id>[0-9]+)$',
        views.DownloadFraudReport.as_view(), name='download_fraud_report'),
]
