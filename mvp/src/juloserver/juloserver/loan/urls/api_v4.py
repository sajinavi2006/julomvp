from __future__ import unicode_literals

from django.conf.urls import url

from rest_framework import routers

from juloserver.loan.views import views_api_v4 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^loan-duration', views.LoanCalculationView.as_view()),
    url(r'^agreement/loan/(?P<loan_xid>[0-9]+)', views.LoanAgreementDetailsView.as_view()),
    url(r'^agreement/content/(?P<loan_xid>[0-9]+)', views.LoanAgreementContentView.as_view()),
]
