from django.conf.urls import include, url
from rest_framework import routers

from .views import (
    LoginView,
    MerchantApplicationView,
    PartnerLoanUpdateView,
    PartnerTransactionView,
    ReferralCreateView,
    RegistrationView,
)

router = routers.DefaultRouter()


urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^referrals/', ReferralCreateView.as_view()),
    url(r'^auth/login', LoginView.as_view()),
    url(r'^internal/auth/registration', RegistrationView.as_view()),
    url(r'^partner_loans/', PartnerLoanUpdateView.as_view()),
    url(r'^transaction/', PartnerTransactionView.as_view()),
    # seller
    url(r'^applications/merchant/(?P<application_id>[0-9]+)/$', MerchantApplicationView.as_view()),
]
