from django.conf.urls import url
from rest_framework import routers

from juloserver.autodebet.views import views_bni_api_v1 as views
router = routers.DefaultRouter()

urlpatterns = [
    url(r'^activation$', views.BNIActivationView.as_view()),
    url(r'^bind$', views.BNIBindView.as_view()),
    url(r'^unbind$', views.BNIAccountUnbinding.as_view()),
    url(r'^verifyOTP$', views.BNIOtpVerification.as_view()),
    url(r'^reactivate$', views.BNIReactivateView.as_view()),
    url(r'^client_credential/accesstoken$', views.BNIAccessTokenView.as_view()),
]
