from django.conf.urls import url
from rest_framework import routers

from juloserver.integapiv1.views import (
    CallCustomerAiRudderPDSView,
    CallCustomerCootekView,
    CallCustomerNexmoView,
)

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^send/two-way-robocall/$', CallCustomerCootekView.as_view()),
    url(r'^send/one-way-robocall/$', CallCustomerNexmoView.as_view()),
    url(r'^send/ai-rudder-task/$', CallCustomerAiRudderPDSView.as_view()),
]
