from django.conf.urls import url, include
from rest_framework import routers
from juloserver.integapiv1.views import (
    BcaSnapAccessTokenView,
    BcaSnapInquiryBillsView,
    BcaSnapPaymentFlagInvocationView,
)

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^access-token/b2b$',
        BcaSnapAccessTokenView.as_view(),
    ),
    url(
        r'^transfer-va/payment$',
        BcaSnapPaymentFlagInvocationView.as_view(),
    ),
    url(
        r'^transfer-va/inquiry$',
        BcaSnapInquiryBillsView.as_view(),
    ),
]
