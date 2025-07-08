from __future__ import unicode_literals

from django.conf.urls import url

from rest_framework import routers

from juloserver.merchant_financing import views

router = routers.DefaultRouter()

urlpatterns = [
    # api/merchant_financing/v1/loan
    url(r'^loan$', views.MerchantLoan.as_view()),
    url(r'^sphp/content/(?P<application_xid>[0-9]+)', views.SphpContentMerchantFinancing.as_view()),
    url(r'^sphp/sign/(?P<application_xid>[0-9]+)', views.SphpSignMerchantFinancing.as_view()),
    url(r'^range-loan-amount', views.RangeLoanAmountView.as_view()),
    url(r'^loan-duration', views.LoanDurationView.as_view()),
    url(r'^merchant/status/(?P<merchant_xid>[0-9]+)$', views.MerchantApplicationStatusView.as_view()),
    url(r'^loan/agreement', views.ChangeLoanAgreementStatus.as_view()),
    url(r'^account-payment', views.RepaymentInformation.as_view()),
    url(r'^reset-pin', views.ResetPin.as_view()),
    url(r'^agreement/content', views.LoanAgreementContentView.as_view()),
    url(r'^pg-service/callback/transfer-result', views.PgServiceCallbackTransferResult.as_view()),
]
