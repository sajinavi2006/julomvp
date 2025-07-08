from django.conf.urls import url
from rest_framework import routers
from juloserver.payback.views import (
    CimbSnapAccessTokenView,
    CimbSnapInquiryBillsView,
    CimbPaymentNotificationView,
)

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^access-token/b2b$',
        CimbSnapAccessTokenView.as_view(),
    ),
    url(
        r'^transfer-va/inquiry$',
        CimbSnapInquiryBillsView.as_view(),
    ),
    url(
        r'^transfer-va/payment$',
        CimbPaymentNotificationView.as_view(),
    ),
]
