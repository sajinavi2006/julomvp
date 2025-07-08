from django.conf.urls import url
from rest_framework import routers

from juloserver.user_action_logs.views import api_v1 as views
router = routers.DefaultRouter()

urlpatterns = [
    url(r'^submit-logs$', views.SubmitLog.as_view()),
    url(r'^web-logs$', views.WebLog.as_view()),
    url(r'^agent-assign-web-logs$', views.AgentAssignFlowWebLog.as_view()),
]
