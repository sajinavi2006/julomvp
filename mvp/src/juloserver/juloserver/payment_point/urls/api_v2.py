from __future__ import unicode_literals

from django.conf.urls import url

from rest_framework import routers

from juloserver.payment_point.views import views_api_v2

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^inquire/electricity/postpaid',
        views_api_v2.InquireElectricityPostpaid.as_view()
    ),
    url(
        r'^inquire/phone/postpaid',
        views_api_v2.InquireMobilePostpaid.as_view()
    ),
    url(
        r'^inquire/bpjs',
        views_api_v2.InquireBpjs.as_view()
    ),
    url(
        r'^ewallet/category',
        views_api_v2.EwalletCategory.as_view()
    ),
    url(
        r'^product',
        views_api_v2.PaymentProduct.as_view()
    ),
]
