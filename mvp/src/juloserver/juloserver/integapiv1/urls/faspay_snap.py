from django.conf.urls import url, include
from rest_framework import routers
from juloserver.integapiv1.views import (
    FaspaySnapInquiry,
    FaspaySnapPaymentView,
)

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^transfer-va/inquiry$',
        FaspaySnapInquiry.as_view(),
    ),
    url(
        r'^transfer-va/payment$',
        FaspaySnapPaymentView.as_view(),
    ),
]
