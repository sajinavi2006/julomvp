from django.conf.urls import url
from rest_framework import routers

from juloserver.inapp_survey.views import api_v1 as view_api_v1

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^questions/(?P<survey_type>[\w-]+)/$', view_api_v1.GetSurveyQuestion.as_view()),
    url(r'^submit/(?P<survey_type>[\w-]+)/$', view_api_v1.SubmitSurveyQuestion.as_view()),
]
