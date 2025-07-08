from django.conf.urls import include, url
from rest_framework import routers

from juloserver.grab.views import views, ecc_views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),

    # auth endpoints - Badri
    url(r'^login', views.GrabLoginView.as_view()),
    url(r'^register', views.GrabRegisterView.as_view()),
    url(r'^reapply', views.GrabReapplyView.as_view()),
    url(r'^link', views.GrabLinkAccountView.as_view()),
    url(r'^forgot_pin', views.GrabForgotPasswordView.as_view()),
    url(r'^otp_request', views.GrabOTPRequestView.as_view()),
    url(r'^otp_confirmation', views.GrabOTPConfirmationView.as_view()),
    url(r'^otp_misscall_request', views.GrabOTPMiscallRequestView.as_view()),

    # common endpoints - Badri
    url(r'^common/homepage', views.GrabHomepageView.as_view()),
    url(r'^common/dropdown', views.GrabDropdownDataView.as_view()),
    url(r'^common/upload', views.GrabUploadView.as_view()),
    url(r'^common/info_cards', views.GrabInfoCardsView.as_view()),

    # application endpoints - Krishna
    url(r'^application/submit', views.GrabSubmitApplicationView.as_view()),
    url(r'^application_review', views.GrabApplicationReviewView.as_view()),
    url(r'^application/status', views.GrabApplicationStatusView.as_view()),
    url(r'^application/validate_referral_code', views.GrabValidateReferralCodeView.as_view()),

    # loan endpoints - Jerrine
    url(r'^loan_offer', views.GrabLoanOfferView.as_view()),
    url(r'^payment_plans', views.GrabPaymentPlansView.as_view()),
    url(r'^choose_payment_plan', views.GrabChoosePaymentPlanView.as_view()),
    url(r'^loan/get_pre_loan', views.GrabPreLoanDetailView.as_view()),
    url(r'^loan/agreement_summary', views.GrabAgreementSummaryView.as_view()),
    url(r'^loan/agreement_letter', views.GrabAgreementLetterView.as_view()),
    url(r'^loan/payments', views.GrabLoanPaymentsView.as_view()),
    url(r'^loan/payment', views.GrabLoanPaymentDetailView.as_view()),
    url(r'^loan/transaction-detail', views.GrabLoanTransactionDetailView.as_view()),
    # url(r'^loans', views.GrabLoansAccountPaymentView.as_view()),
    url(r'^loans', views.GrabLoansPaymentView.as_view()),
    url(r'^loan_review', views.GrabLoanDetailView.as_view()),
    url(r'^loan$', views.GrabLoanApplyView.as_view()),
    url(r'^loan/image_upload/v1/(?P<loan_xid>[0-9]+)/$', views.GrabLoanSignatureUploadView.as_view()),

    # partner api endpoints - Jerrine
    url(r'^account_summary', views.GrabAccountSummaryView.as_view()),
    url(r'^repayment', views.GrabAddRepaymentView.as_view()),
    url(r'^julo_homepage', views.GrabHomePageIntegrationApiView.as_view()),

    # account page api endpoints
    url(r'^account-page', views.GrabAccountPageView.as_view()),
    url(r'^verify-pin', views.GrabVerifyPINView.as_view()),
    url(r'^change-pin', views.GrabChangePINView.as_view()),
    url(r'^referral-info', views.GrabReferralInfoView.as_view()),

    url(r'^grab_bank_check', views.GrabBankCheckView.as_view()),  # DEPRICATED
    url(r'^application/verify-grab-bank-account',
        views.GrabBankPredisbursalCheckView.as_view()),

    # feature-settings
    url(r'^feature-settings$', views.GrabFeatureSettingView.as_view()),
    url(r'^get_grab_reregister_status$', views.GrabGetReapplyStatusView.as_view()),


    url(r'^change_phone/check_grab_phone$', views.GrabCheckPhoneNumberView.as_view()),
    url(r'^change_phone/otp_request$', views.GrabChangePhoneOTPRequestView.as_view()),
    url(r'^change_phone/otp_confirmation$', views.GrabChangePhoneOTPConfirmationView.as_view()),
    url(r'^change_phone/change_phone_number$', views.GrabChangePhoneNumberView.as_view()),
    url(r'^get-bulk-loan-data$', views.GrabGetAuditDataFromOSSView.as_view()),

    # Application Long Form Revamp API's
    url(r'^address/provinces$', views.GrabAddressLookupView.as_view({"get": "get_provinces"})),
    url(r'^address/cities$', views.GrabAddressLookupView.as_view({"get": "get_cities"})),
    url(r'^address/districts$', views.GrabAddressLookupView.as_view({"get": "get_districts"})),
    url(r'^address/subdistricts$', views.GrabAddressLookupView.as_view({"get": "get_subdistricts"})),
    url(r'^address/info$', views.GrabAddressLookupView.as_view({"get": "get_info"})),
    url(r'application/form/load$', views.GrabPopulateLongFormData.as_view()),
    url(r'application/form$', views.GrabDropdownDataView.as_view()),
    url(r'application/v2/submit$', views.GrabSubmitApplicationV2View.as_view()),

    url(r'get-user-bank-account$', views.GrabUserBankAccountDetailsView.as_view()),
    # bank rejection flow
    url(r'change-bank-account/$', views.GrabChangeBankAccountView.as_view()),
    url(r'change-bank-account/status$', views.GrabChangeBankAccountView.as_view()),
    url(r'validate-promo-code$', views.GrabValidatePromoCodeView.as_view()),

    # experiment group
    url(r'user-experiment-group$', views.GrabUserExperimentDetailsView.as_view()),
    # emergency contact
    url(
        r'^emergency-contact-(?P<unique_code>[a-zA-Z_0-9]+)$',
        ecc_views.GrabEmergencyContactDetailView.as_view(),
    ),
    url(
        r'^emergency-contact/$',
        ecc_views.GrabEmergencyContactView.as_view(),
    ),
]
