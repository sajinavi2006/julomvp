from django.conf.urls import url
from rest_framework import routers

from juloserver.cx_complaint_form.views import api_v1 as view_api_v1

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^topics/$', view_api_v1.GetComplaintTopics.as_view()),
    url(
        r'^topics/(?P<topic_slug>[\w-]+)/sub-topics/$', view_api_v1.GetComplaintSubTopics.as_view()
    ),
    url(r'^submit/$', view_api_v1.SubmitComplaint.as_view()),
    url(r'^suggested-answers/$', view_api_v1.GetSuggestedAnswers.as_view()),
    url(r'^suggested-answers/feedback/$', view_api_v1.SubmitFeedbackSuggestedAnswers.as_view()),
]
