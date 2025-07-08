from django.conf.urls import include, url
from rest_framework import routers

from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    # api to get server time
    url(r'^status-labels$', views.StatusLabelsView.as_view()),
    url(r'^bank-account-validation$', views.BankAccountValidationView.as_view()),
    url(r'^cashback-to-gopay$', views.CashBackToGopay.as_view()),
    url(r'^banner$', views.BannersView.as_view()),
    url(
        r'^gopay-phone-number-change-otp-request', views.GopayPhoneNumberChangeRequestOTP.as_view()
    ),
    url(r'^gopay-validate-otp', views.GopayValidateOTPView.as_view()),
    url(r'^gopay-update-phone-number', views.GopayUpdatePhoneNumberView.as_view()),
]
