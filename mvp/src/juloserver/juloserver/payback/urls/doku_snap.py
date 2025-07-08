from django.conf.urls import url
from rest_framework import routers
from juloserver.payback.views import (
    DokuSnapAccessTokenView,
    DokuSnapInquiryBillsView,
    DokuSnapPaymentNotificationView,
)

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^authorization/v1/access-token/b2b$',
        DokuSnapAccessTokenView.as_view(),
    ),
    url(
        r'^v1.1/transfer-va/inquiry$',
        DokuSnapInquiryBillsView.as_view(),
    ),
    url(r'^v1.1/transfer-va/payment$', DokuSnapPaymentNotificationView.as_view()),
]
