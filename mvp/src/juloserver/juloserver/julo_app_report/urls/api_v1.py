from django.conf.urls import url
from rest_framework import routers
from juloserver.julo_app_report.views import view_api_v1 as views


router = routers.DefaultRouter()

urlpatterns = [
    url(r'^crash-report', views.CaptureJuloAppReport.as_view()),
]
