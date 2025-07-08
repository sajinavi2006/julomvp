from __future__ import unicode_literals

from django.conf.urls import include, url
from rest_framework import routers

from . import views, web_views

router = routers.DefaultRouter()

web_urls_v1 = [
    url(r'^register', web_views.RegisterJuloOneUser.as_view()),
    url(r'^login', web_views.LoginJuloOne.as_view()),
]

web_urls = [
    url(r'^v1/', include(web_urls_v1)),
]

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^web/', include(web_urls)),
    url(r'^v1/register', views.RegisterJuloOneUser.as_view()),
    url(r'^v1/checkpincustomer', views.CheckPinCustomer.as_view()),
    url(r'^v1/login', views.LoginJuloOne.as_view()),
    url(r'^v1/reset/request', views.ResetPin.as_view()),
    url(r'^v1/reset/confirm/(?P<reset_key>.+)/$', views.ResetPinConfirm.as_view()),
    url(
        r'^v1/reset-by-phone-number/confirm/(?P<reset_key>.+)/$',
        views.ResetPinConfirmByPhoneNumber.as_view(),
    ),
    url(r'^v1/setup-pin', views.SetupPin.as_view()),
    url(r'^v1/check_pin', views.CheckCurrentPin.as_view()),
    url(r'^v1/change_pin', views.ChangeCurrentPin.as_view()),
    url(r'^v1/check-strong-pin', views.CheckStrongPin.as_view(), name='check_strong_pin'),
    url(r'^v1/preregister-check', views.PreRegisterCheck.as_view()),
    url(r'^v1/pre-check-pin$', views.PreCheckPin.as_view()),
    url(r'^v2/login', views.Login.as_view()),
    url(r'^v2/reset/request', views.ResetPassword.as_view()),
    url(r'^v2/check-pin', views.CheckCurrentPinV2.as_view()),
    url(r'^v2/register', views.RegisterJuloOneUserV2.as_view()),
    url(r'^v3/reset/request', views.ResetPinv3.as_view()),
    url(r'^v4/reset/request', views.ResetPinv4.as_view()),
    url(r'^v5/reset/request', views.ResetPinv5.as_view()),
    url(r'^v3/login', views.LoginV2.as_view()),
    url(r'^v4/login', views.LoginV3.as_view()),
    url(r'^v5/login', views.LoginV4.as_view()),
    url(r'^v6/login', views.LoginV6.as_view()),
    url(r'^v7/login', views.LoginV7.as_view()),
    url(r'^v1/partner/login', views.LoginPartner.as_view()),
    url(r'^v1/reset-count', views.CustomerResetCount.as_view()),
    url(
        r'^v1/reset/phone/verify/(?P<reset_key>.+)/$', views.ResetPinPhoneVerificationAPI.as_view()
    ),
]
