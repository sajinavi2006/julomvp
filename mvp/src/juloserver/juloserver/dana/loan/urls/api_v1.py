from django.conf.urls import url
from rest_framework import routers
from juloserver.dana.loan import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^debit/payment-host-to-host', views.DanaPaymentView.as_view(), name="payment"),
    url(
        r'^agreement/content/(?P<encrypted_loan_xid>[A-Za-z0-9=]+)$',
        views.DanaAgreementContentView.as_view(),
        name="loan-agreement-content",
    ),
    url(r'^debit/status', views.DanaLoanStatusView.as_view(), name="loan-status"),
]
