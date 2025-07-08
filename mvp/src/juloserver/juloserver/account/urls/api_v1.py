from __future__ import unicode_literals

from django.conf.urls import url
from rest_framework import routers

from .. import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^account-payment/dpd', views.AccountPaymentDpd.as_view()),
    url(r'^account-payment', views.AccountPaymentList.as_view()),
    url(r'^image', views.ImageAccountPayment.as_view()),
    url(r'^loans/$', views.AccountLoansView.as_view()),
    url(r'^loan/amount/$', views.AccountLoansAmountView.as_view()),
    url(
        r'^address/customer/(?P<customer_id>[0-9]+)',
        views.get_additional_address,
        name='get_additional_address',
    ),
    url(r'^address/customer', views.store_additional_address, name='store_additional_address'),
    url(
        r'^address/(?P<pk>[0-9]+)',
        views.update_additional_address,
        name='update_additional_address',
    ),
    url(
        r'^delete-address/(?P<pk>[0-9]+)',
        views.delete_additional_address,
        name='delete_additional_address',
    ),
    url(r'^active-payment', views.ActivePaymentCheckout.as_view()),
    url(r'^checkout-faq', views.FAQCheckoutList.as_view()),
    # zendesk
    url(r'^zendesk-token/', views.ZendeskJwtTokenGenerator.as_view()),
    url(r'^chatbot-token/', views.ChatBotTokenGenerator.as_view()),
    url(r'^cashback-potential', views.PotentialCashbackList.as_view()),
    url(r'^tagihan-revamp-experiment$', views.TagihanRevampExperimentView.as_view()),
    url(r'^loans/(?P<loan_xid>[0-9]+)/payment-list/$', views.PaymentListView.as_view()),
    # cashback claim
    url(r'^cashback-claim/claim', views.CashbackClaimInfoCard.as_view()),
    url(r'^cashback-claim/check', views.CashbackClaimCheck.as_view()),
]
