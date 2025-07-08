from django.conf.urls import include, url
from rest_framework import routers
from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^smart_call/(?P<username>\w{0,50})/$', views.HomePageView.as_view()),
    url(r'^answer_url/(?P<userid>[0-9]+)/$', views.AnswerUrlView.as_view(), name="nexmo-answer-url"),
    url(r'^call_queue/$', views.CallQueueView.as_view()),
    url(r'^call_status/$', views.CallStatusView.as_view()),
]
