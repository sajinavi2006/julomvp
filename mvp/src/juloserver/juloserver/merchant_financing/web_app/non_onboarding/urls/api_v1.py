from django.conf.urls import url
from rest_framework import routers
from juloserver.merchant_financing.web_app.non_onboarding import views

router = routers.DefaultRouter()

urlpatterns = [
    # API For Merchant Financing non onboarding (Partner/Agent Auth) - AGENT SESSION
    url(
        r'^distributor',
        views.WebAppNonOnboardingDistributorListView.as_view(),
        name="list_distributor",
    ),
    url(r'^(?P<loan_xid>[0-9]+)', views.WebAppNonOnboardingLoan.as_view(), name="agent_loan"),
    url(
        r'^(?P<loan_xid>[0-9]+)/calculate',
        views.WebAppNonOnboardingLoanCalculationView.as_view(),
        name="loan_calculation",
    ),
]
