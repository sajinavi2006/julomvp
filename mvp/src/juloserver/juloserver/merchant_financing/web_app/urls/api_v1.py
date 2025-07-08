from django.conf.urls import url
from rest_framework import routers
from juloserver.merchant_financing.web_app import views

router = routers.DefaultRouter()

urlpatterns = [
    # Axiata OJK section
    url(r'^(?P<partner>[a-z0-9A-Z_-]+)/register', views.WebAppRegister.as_view(), name="register"),
    url(r'^login', views.LoginWebApp.as_view(), name="login"),
    url(r'^token/refresh', views.RetriveNewAccessToken.as_view(), name='refresh-token'),
    url(r'^logout', views.Logout.as_view(), name='logout'),
    url(r'^address/provinces$', views.WebviewAddressLookupView.as_view({"get": "get_provinces"})),
    url(r'^address/cities$', views.WebviewAddressLookupView.as_view({"get": "get_cities"})),
    url(r'^address/districts$', views.WebviewAddressLookupView.as_view({"get": "get_districts"})),
    url(
        r'^address/subdistricts$',
        views.WebviewAddressLookupView.as_view({"get": "get_subdistricts"}),
    ),
    url(r'^address/info$', views.WebviewAddressLookupView.as_view({"get": "get_info"})),
    url(
        r'^dropdown/marital-statuses$',
        views.WebviewDropdownDataView.as_view({"get": "get_marital_statuses"}),
    ),
    url(
        r'^(?P<partner>[a-z0-9A-Z_-]+)/applications',
        views.ListApplications.as_view(),
        name="applications",
    ),
    url(r'^profile', views.WebAppMerchantUserProfile.as_view(), name='user-profile'),
    url(r'^otp/request', views.WebAppOTPRequest.as_view(), name='web_app_otp_request'),
    url(r'^otp/verify', views.WebAppVerifyOtp.as_view(), name='web_app_verify-otp'),
    url(r'^(?P<partner>[a-z0-9A-Z_-]+)/upload', views.UploadDocumentView.as_view(), name="upload"),
    url(
        r'^(?P<partner>[a-z0-9A-Z_-]+)/delete$',
        views.DocumentDeleteAllView.as_view(),
        name="delete_docs",
    ),
    url(
        r'^(?P<partner>[a-z0-9A-Z_-]+)/delete/(?P<id>[a-z0-9_]+)$',
        views.DocumentDeleteByIDView.as_view(),
        name="delete_docs",
    ),
    url(
        r'^(?P<partner>[a-z0-9A-Z_-]+)/submit',
        views.SubmitApplicationView.as_view(),
        name="submit_application",
    ),
    url(
        r'^password/reset/request$',
        views.WebAppForgotPasswordView.as_view(),
        name='web-app-request-forgot-password',
    ),
    url(
        r'^password/reset/verify-token$',
        views.WebAppVerifyRestKeyView.as_view(),
        name='web-app-verify-token-forgot-password',
    ),
    url(
        r'^password/reset$',
        views.WebAppResetPasswordConfirmView.as_view(),
        name='web-app-password-confirm',
    ),
]
