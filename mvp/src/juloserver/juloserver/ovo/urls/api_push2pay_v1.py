from django.conf.urls import url

from rest_framework import routers

from juloserver.ovo.views import ovo_push2pay_views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^transaction', ovo_push2pay_views.TransactionDataView.as_view()),
    url(r'^push-to-pay', ovo_push2pay_views.PushToPayView.as_view()),
    url(r'^notification', ovo_push2pay_views.NotificationCallbackView.as_view()),
    url(
        r'^payment/status/(?P<transaction_id>[0-9]+)$',
        ovo_push2pay_views.PaymentStatusView.as_view(),
    ),
]
