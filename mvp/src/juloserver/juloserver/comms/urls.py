from django.conf.urls import url
from rest_framework import routers
from juloserver.comms.views import email_v1


router = routers.DefaultRouter()

urlpatterns = [
    url(r'^v1/email/callback', email_v1.EventCallbackView.as_view()),
]
