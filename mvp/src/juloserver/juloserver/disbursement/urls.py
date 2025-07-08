from __future__ import unicode_literals

from django.conf.urls import url
from rest_framework import routers

from juloserver.disbursement.views.views_api_v1 import (
    XenditNameValidateEventCallbackView,
    XenditDisburseEventCallbackView,
    XfersDisburseEventCallbackView,
    InstamoneyDisburseEventCallbackView,
    PaymentGatewayDisburseEventCallbackView,
)
from juloserver.disbursement.views.views_api_v2 import (
    XenditDisburseEventCallbackViewV2,
)

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^callbacks/xendit_name_validate$',
        XenditNameValidateEventCallbackView.as_view()),
    url(r'^callbacks/xendit_disburse$', XenditDisburseEventCallbackView.as_view()),
    url(r'^callbacks/xfers-disburse$', XfersDisburseEventCallbackView.as_view()),
    url(r'^callbacks/instamoney-disburse$', InstamoneyDisburseEventCallbackView.as_view()),

    # v2
    url(r'^callbacks/v2/xendit-disburse$', XenditDisburseEventCallbackViewV2().as_view()),
    url(
        r'^callbacks/v1/payment-gateway-disburse$',
        PaymentGatewayDisburseEventCallbackView.as_view(),
    ),
]
