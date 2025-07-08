from django.conf.urls import url
from rest_framework import routers
from juloserver.merchant_financing.web_app.non_onboarding import views

router = routers.DefaultRouter()

urlpatterns = [
    # API For Merchant Financing Web App - Non Onboarding - MERCHANT SESSION
    url(
        r'^loan/(?P<loan_xid>[0-9]+)/skrtp/sign',
        views.WebAppNonOnboardingSignSkrtpView.as_view(),
        name="loan_sign_skrtp",
    ),
    url(
        r'loan/(?P<loan_xid>[0-9]+)/skrtp',
        views.WebAppNonOnboardingShowSkrtpView.as_view(),
        name="loan_show_skrtp",
    ),
    url(
        r'loan/(?P<loan_xid>[0-9]+)/digisign/status',
        views.WebAppNonOnboardingDigisignStatus.as_view(),
        name="loan_digisign_status",
    ),
    url(r'^loan/create', views.WebAppNonOnboardingCreateLoan.as_view(), name="loan_create"),
    url(
        r'loan/(?P<loan_xid>[0-9]+)',
        views.WebAppNonOnboardingLoanDetail.as_view(),
        name="loan_detail",
    ),
    url(r"^loan/", views.WebAppNonOnboardingLoanListView.as_view(), name="loan_list"),
    url(
        r"^max-platform-check/",
        views.WebAppNonOnboardingMaxPlatformCheckView.as_view(),
        name="max-platform-check",
    ),
]
