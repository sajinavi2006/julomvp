from __future__ import unicode_literals

from django.conf.urls import url

from rest_framework import routers

from juloserver.payment_point.views import views_api_v1

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^mobile-operator',
        views_api_v1.MobileOperatorView.as_view()
    ),
    url(
        r'^mobile-phone-validate',
        views_api_v1.MobilePhoneValidateView.as_view()
    ),
    url(
        r'^product',
        views_api_v1.PaymentProduct.as_view()
    ),
    url(
        r'^inquiry-electricity',
        views_api_v1.InquiryElectricityInformation.as_view()
    ),
    url(
        r'^pulsa-transaction-histories',
        views_api_v1.PulsaTransactionHistory.as_view()
    ),
    url(
        r'^paket-data-transaction-histories',
        views_api_v1.PaketDataTransactionHistory.as_view()
    ),
    url(r'^phone-recommendation', views_api_v1.PhoneRecommendationView.as_view()),
    url(r'^inquiry-internet-bill', views_api_v1.InquiryInternetBillInfoView.as_view()),
]
