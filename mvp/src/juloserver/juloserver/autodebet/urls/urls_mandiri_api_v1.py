from django.conf.urls import url
from rest_framework import routers

from juloserver.autodebet.views import views_mandiri_api_v1 as views
router = routers.DefaultRouter()

urlpatterns = [
    url(r'^deactivation$', views.MandiriAccountDeactivationView.as_view()),
    url(r'^request-otp$', views.RequestOTPView.as_view()),
    url(r'^verify-otp$', views.VerifyOTPView.as_view()),
    url(r'^activation$', views.ActivationView.as_view()),
    url(r'^check-callback-activation', views.CheckCallbackActivation.as_view()),
    url(r'^reactivate$', views.ReactivateView.as_view()),
]
