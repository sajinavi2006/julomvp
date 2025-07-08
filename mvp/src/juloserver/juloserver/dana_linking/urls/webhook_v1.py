from django.conf.urls import url
from rest_framework import routers
from juloserver.dana_linking import views

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^payment_notification$',
        views.DanaPaymentNotificationView.as_view(),
        name="payment_notification",
    ),
    url(
        r'^unbind_notification$',
        views.DanaUnbindNotificationView.as_view(),
        name="unbind_notification",
    ),
]
