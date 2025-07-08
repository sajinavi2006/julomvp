from django.conf.urls import url
from rest_framework import routers

from juloserver.autodebet.views import views_bri_api_v1 as views
router = routers.DefaultRouter()

urlpatterns = [
    url(r'^registration$', views.BRIAccountRegistrationView.as_view()),
    url(r'^otp/verify/activation$', views.BRIRegistrationOTPVerifyView.as_view()),
    url(r'^otp/verify/transaction$', views.BRITransactionOTPVerifyView.as_view()),
    url(r'^callback/transaction$', views.BRITransactionCallbackView.as_view()),
    url(r'^reset$', views.BRIAccountResetView.as_view()),
    url(r'^otp/request/transaction$', views.BRITransactionRequestOTPView.as_view()),
    url(r'^deactivation$', views.BRIDeactivationView.as_view()),
    url(r'^reactivate$', views.ReactivateView.as_view()),
]
