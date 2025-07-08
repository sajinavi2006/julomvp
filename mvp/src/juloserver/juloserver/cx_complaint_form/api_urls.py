from django.conf.urls import url

from juloserver.cx_complaint_form.views import api_v1 as views

urlpatterns = [
    url(r'^v1/topics/$', views.GetComplaintTopics.as_view()),
    url(r'^v1/topics/(?P<topic_slug>[\w-]+)/sub-topics/$', views.GetComplaintSubTopics.as_view()),
    url(r'^v1/submit/$', views.SubmitComplaint.as_view()),
]
