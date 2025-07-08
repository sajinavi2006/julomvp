from django.conf.urls import url
from rest_framework import routers

from juloserver.inapp_survey.views import web_v1 as view_web_v1

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^questions/(?P<survey_type>[\w-]+)/$', view_web_v1.WebGetSurveyQuestion.as_view()),
    url(r'^submit/(?P<survey_type>[\w-]+)/$', view_web_v1.WebSubmitSurveyQuestion.as_view()),
]
