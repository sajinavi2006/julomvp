from django.conf.urls import url
from rest_framework import routers
from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^v1/nps_survey/$', views.NPSSurveyAPIView.as_view(), name='nps_survey'),
]
