from django.conf.urls import url
from rest_framework import routers
from juloserver.partnership.leadgenb2b.onboarding import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'profile', views.ProfileView.as_view(), name="profile"),
    url(
        r'pre-check/register',
        views.LeadgenStandardPreRegister.as_view(),
        name="pre-check-register",
    ),
    url(r'pin/check', views.LeadgenStandardPinCheck.as_view(), name="pin-check"),
    url(r'register$', views.RegisterView.as_view(), name="registration"),
    url(r'configs', views.LeadgenConfigsView.as_view(), name="configs"),
    url(r'logout', views.LeadgenLogoutView.as_view(), name="logout"),
    url(r'login$', views.LeadgenLoginView.as_view(), name="leadgen-login"),
    url(
        r'^form/address/provinces',
        views.LeadgenStandardProvinceView.as_view(),
        name="address-provinces",
    ),
    url(
        r'^form/address/regencies',
        views.LeadgenStandardRegencyView.as_view(),
        name="address-cities",
    ),
    url(
        r'^form/address/districts',
        views.LeadgenStandardDistrictView.as_view(),
        name="address-districts",
    ),
    url(
        r'^form/address/subdistricts',
        views.LeadgenStandardSubDistrictView.as_view(),
        name="address-subdistricts",
    ),
    url(r'^form/address/info', views.LeadgenStandardAddressInfoView.as_view(), name="address-info"),
    url(
        r'^form/dropdown/job-type',
        views.LeadgenStandardJobTypeView.as_view(),
        name="dropdown-job-type",
    ),
    url(
        r'^form/dropdown/job-industry',
        views.LeadgenStandardJobIndustryView.as_view(),
        name="dropdown-job-industry",
    ),
    url(
        r'^form/dropdown/job-position',
        views.LeadgenStandardJobPositionView.as_view(),
        name="dropdown-job-position",
    ),
    url(
        r'^form/dropdown/emergency-contact',
        views.LeadgenStandardEmergencyContactTypeView.as_view(),
        name="dropdown-emergency-contact",
    ),
    url(
        r'^form/dropdown/home-status',
        views.LeadgenStandardHomeStatusTypeView.as_view(),
        name="dropdown-home-status",
    ),
    url(
        r'^form/dropdown/marital-status',
        views.LeadgenStandardMaritalStatusTypeView.as_view(),
        name="dropdown-marital-status",
    ),
    url(r'^form/dropdown/banks', views.LeadgenStandardBanksView.as_view(), name="dropdown-banks"),
    url(
        r'^form/dropdown/loan-purpose',
        views.LeadgenStandardLoanPurposeView.as_view(),
        name="dropdown-loan-purpose",
    ),
    url(
        r'otp/login/request',
        views.LeadgenLoginOtpRequestView.as_view(),
        name="leadgen-login-otp-request",
    ),
    url(r'forgot-pin', views.LeadgenForgotPin.as_view(), name="leadgen-forgot-pin"),
    url(
        r"^pin/data",
        views.LeadgenPinFetchCustomerData.as_view(),
        name="pin-fetch-customer-data",
    ),
    url(
        r'^pin/reset$',
        views.LeadgenStandardResetPin.as_view(),
        name="reset-pin",
    ),
    url(
        r'^pin/change$',
        views.LeadgenStandardChangePinSubmission.as_view(),
        name="change-pin",
    ),
    url(
        r'otp/login/verify',
        views.LeadgenLoginOtpVerifyView.as_view(),
        name="leadgen-login-otp-verify",
    ),
    url(
        r"^form/upload/(?P<image_type>(ktp|ktp-selfie))$",
        views.LeadgenStandardUploadImage.as_view(),
        name="upload-image",
    ),
    url(
        r"image/(?P<image_id>[0-9]+)$",
        views.LeadgenStandardGetImage.as_view(),
        name="get-image",
    ),
    url(
        r'otp/phone-number/request$',
        views.LeadgenPhoneOtpRequestView.as_view(),
        name="leadgen-phone-otp-request",
    ),
    url(
        r'otp/phone-number/verify$',
        views.LeadgenPhoneOtpVerifyView.as_view(),
        name="leadgen-phone-otp-verify",
    ),
    url(r'^pin/verify$', views.LeadgenStandardChangePinVerification.as_view(), name="pin-verify"),
    url(
        r'^otp/change-pin/request$',
        views.LeadgenStandardChangePinOTPRequestView.as_view(),
        name="otp-change-pin-request",
    ),
    url(
        r'^otp/change-pin/verify$',
        views.LeadgenStandardChangePinOTPVerification.as_view(),
        name="otp-change-pin-verify",
    ),
    url(
        r'additional-documents/submit$',
        views.LeadgenSubmitMandatoryDocsView.as_view(),
        name="leadgen-submit-mandatory-docs-x120",
    ),
    url(
        r'otp/register/verify$',
        views.LeadgenRegisterOtpVerifyView.as_view(),
        name="leadgen-register-otp-verify",
    ),
    url(
        r'otp/register/request',
        views.LeadgenRegisterOtpRequestView.as_view(),
        name="leadgen-register-otp-request",
    ),
    url(
        r'^liveness/submit$',
        views.LeadgenSubmitLivenessView.as_view(),
        name="leadgen-submit-liveness",
    ),
    url(r'^form$', views.LeadgenStandardGetFormData.as_view(), name="get-form"),
    url(
        r'^form/submit$',
        views.LeadgenSubmitApplicationView.as_view(),
        name="leadgen-submit-application",
    ),
    url(
        r'^resubmission/request',
        views.LeadgenResubmissionApplicationView.as_view(),
        name="leadgen-resubmission-application",
    ),
    url(
        r'^reapply$',
        views.LeadgenStandardReapplyView.as_view(),
        name="reapply",
    ),
    url(
        r"^mandatory-docs/(?P<image_type>(ktp|ktp-selfie|payslip|bank-statement))/upload",
        views.LeadgenStandardUploadMandatoryDocs.as_view(),
        name="upload-mandatory-docs",
    ),
    url(
        r'form/phone-number/check',
        views.LeadgenFormPhoneNumberCheck.as_view(),
        name="leadgen-form-phone-number-check",
    ),
]
