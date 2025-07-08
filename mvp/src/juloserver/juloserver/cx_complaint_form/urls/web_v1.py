from django.conf.urls import url
from rest_framework import routers

from juloserver.cx_complaint_form.views import web_v1 as view_web_v1

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^topics/$', view_web_v1.WebGetComplaintTopics.as_view()),
    url(
        r'^topics/(?P<topic_slug>[\w-]+)/sub-topics/$',
        view_web_v1.WebGetComplaintSubTopics.as_view(),
    ),
    url(r'^submit/$', view_web_v1.WebSubmitComplaint.as_view()),
    url(r'^suggested-answers/$', view_web_v1.GetWebSuggestedAnswers.as_view()),
    url(r'^suggested-answers/feedback/$', view_web_v1.WebSubmitFeedbackSuggestedAnswers.as_view()),
    url(r'^get-ip/$', view_web_v1.GetIPClientAddress.as_view()),
]
