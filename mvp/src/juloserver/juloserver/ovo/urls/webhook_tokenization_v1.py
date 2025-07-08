from django.conf.urls import url

from rest_framework import routers

from juloserver.ovo.views import ovo_tokenization_views as views

router = routers.DefaultRouter()

urlpatterns = [
    # b2b token already implemented on doku va
    url(r'^binding-notification$', views.OvoBindingNotificationView.as_view()),
    url(r'^debit/notify', views.OvoTokenizationPaymentNotification.as_view()),
]
