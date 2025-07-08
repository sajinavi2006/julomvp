from __future__ import unicode_literals

from django.conf.urls import url

from rest_framework import routers

from juloserver.loan.views import views_api_v3 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^loan-duration',
        views.LoanCalculation.as_view()
    ),
    url(
        r'^loan',
        views.LoanJuloOne.as_view()
    ),
    url(r'^range-loan-amount/(?P<account_id>[0-9]+)$', views.RangeLoanAmount.as_view()),
    url(r'^one-click-repeat', views.OneClickRepeatView.as_view()),
    url(r'^agreement/loan/(?P<loan_xid>[0-9]+)', views.LoanAgreementDetailsView.as_view()),
    url(r'^agreement/content/(?P<loan_xid>[0-9]+)', views.LoanAgreementContentView.as_view()),
    # delayed disbursement
    url(r'^delayed-disbursement/content$', views.DelayedDisbursementContentView.as_view()),
]
