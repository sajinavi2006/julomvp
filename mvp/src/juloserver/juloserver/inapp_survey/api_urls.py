from django.conf.urls import url
from rest_framework import routers

from . import api_views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^v1/questions/(?P<survey_type>[\w-]+)/$', api_views.GetSurveyQuestion.as_view()),
    url(r'^v1/submit/(?P<survey_type>[\w-]+)/$', api_views.SubmitSurveyQuestion.as_view()),
]
