from django.conf.urls import url
from rest_framework import routers
from juloserver.partnership import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^application/(?P<application_xid>[0-9]+)$', views.SubmitApplicationView.as_view()),
    url(r'^customer', views.CustomerRegistrationView.as_view()),
    url(r'^partner', views.PartnerRegistrationView.as_view()),
    url(r'^address$', views.AddressLookupView.as_view()),
    url(r'^application/otp/(?P<application_xid>[0-9]+)$', views.ApplicationOtpRequest.as_view()),
    url(r'^application/otp/validate/(?P<application_xid>[0-9]+)$',
        views.ApplicationOtpValidation.as_view()),
    url(r'^preregister-check', views.PreRegisterCheck.as_view()),
    url(r'^check-strong-pin', views.CheckStrongPin.as_view()),
    url(r'^pin/verify', views.PinVerify.as_view()),
    url(r'^applications/(?P<application_xid>[0-9]+)/images$', views.ImageListCreateView.as_view()),
    url(r'^loan/(?P<loan_xid>[0-9]+)/images$', views.LoanImageListCreateView.as_view()),
    url(r'^dropdowns', views.DropdownDataView.as_view()),
    url(r'^external-data-imports/(?P<application_xid>[0-9]+)$', views.BankScraping.as_view()),
    url(r'^scraping-status/(?P<application_xid>[0-9]+)$',
        views.ScrapingStatusGet.as_view()),
    url(r'^merchant-partner$', views.MerchantPartnerWithProductLineView.as_view()),
    url(r'^merchants/initial-application$', views.MerchantRegistrationView.as_view()),
    url(r'^bpjs/login/(?P<application_xid>[0-9]+)/(?P<app_type>.*)$',
        views.BpjsLoginUrlView.as_view()),
    url(r'^submit-document-flag/(?P<application_xid>[0-9]+)$',
        views.SubmitDocumentFlagView.as_view()),
    url(r'^application/status/(?P<application_xid>[0-9]+)$',
        views.ApplicationStatusView.as_view()),

    # Partnership LeadGen Loan API's
    url(r'^range-loan-amount/(?P<application_xid>[0-9]+)$', views.RangeLoanAmountView.as_view()),
    url(r'^loan-duration/(?P<application_xid>[0-9]+)$', views.LoanDurationView.as_view()),
    url(r'^agreement/content/(?P<loan_xid>[0-9]+)/',
        views.LoanPartnershipAgreementContentView.as_view()),
    url(r'agreement/loan/status/(?P<loan_xid>[0-9]+)/',
        views.ChangePartnershipLoanStatusView.as_view()),
    url(r'^loan/(?P<application_xid>[0-9]+)', views.LoanPartner.as_view()),
    url(r'loan/status/(?P<loan_xid>[0-9]+)/',
        views.LoanStatusView.as_view()),
    url(r'^bank/partner/validate', views.ValidatePartnershipBankAccount.as_view()),
    url(r'^bank/partner', views.PartnershipBankAccount.as_view()),
    url(r'^bank/(?P<application_xid>[0-9]+)', views.BankAccountDestination.as_view()),

    url(r'^account-payment/(?P<application_xid>[0-9]+)', views.RepaymentInformation.as_view()),
    url(r'^image/(?P<encrypted_image_id>[A-Za-z0-9=]+)$', views.ShowImage.as_view(),
        name='image_process'),
    url(r'^merchants/applications/(?P<application_xid>[0-9]+)',
        views.MerchantApplication.as_view()),
    url(r'^merchants/transactions/v2/(?P<application_xid>[0-9]+)',
        views.MerchantHistoricalTransactionV2View.as_view()),
    url(r'^merchants/transactions/(?P<application_xid>[0-9]+)',
        views.MerchantHistoricalTransactionView.as_view()),
    url(r'^merchants/transactions/status/(?P<historical_transaction_task_unique_id>[0-9]+)',
        views.MerchantHistoricalTransactionUploadStatusView.as_view()),
    url(r'^merchants$', views.MerchantView.as_view()),
    url(r'^distributors', views.DistributorView.as_view()),
    url(r'^create-pin', views.CreatePinView.as_view()),
    url(r'^input-pin', views.InputPinView.as_view()),

    # get total binary check score
    url(r'^merchant/get_total_binary_check_score',
        views.MerchantBinaryScoreCheckView.as_view(), name='get_total_binary_check_score'),

    # Whitelabel API's
    url(r'^whitelabel-paylater-register', views.WhitelabelPartnerRegistrationView.as_view()),
    url(r'^whitelabel-handshake', views.InitializationStatusView.as_view()),
    url(r'^whitelabel-unlink-account/(?P<application_xid>[0-9]+)$',
        views.WhitelabelUnlinkView.as_view()),
    url(r'^whitelabel-status-summary/(?P<application_xid>[0-9]+)$',
        views.WhitelabelStatusSummaryView.as_view()),

    url(r'^confirm-pin/(?P<application_xid>[0-9]+)$', views.ConfirmPinUrlView.as_view()),
    url(r'^loan-offer$', views.LoanOfferView.as_view()),

    url(r'^retry-check-transaction-status', views.PartnershipRetryCheckTransactionView.as_view()),
    url(r'^transaction-status-logs$', views.PartnershipLogTransactionView.as_view()),
    url(r'^transaction-details$',
        views.PaylaterTransactionDetailsView.as_view()),
    url(r'^paylater-transaction-status$', views.PaylaterTransactionStatusView.as_view()),
    url(r'loan/receipt/(?P<loan_xid>[0-9]+)/',
        views.GetPartnerLoanReceiptView.as_view()),
    url(r'^whitelabel-paylater-create-pin$', views.WhitelabelCreatePinView.as_view()),

    # Leadgen API's
    url(r'^address/provinces', views.PartnershipGetProvinceView.as_view()),
    url(r'^address/cities', views.PartnershipGetCityView.as_view()),
    url(r'^address/districts', views.PartnershipGetDistrictView.as_view()),
    url(r'^address/subdistricts', views.PartnershipGetSubDistrictView.as_view()),
    url(r'^address/info', views.PartnershipGetAddressInfoView.as_view()),
    url(r'^data/additional-info', views.PartnershipAdditionalInfoView.as_view()),
    url(r'^data/bank', views.DropDownBanks.as_view()),
    url(r'^data/job', views.DropDownJobs.as_view()),
    url(r'^register/email/otp/request$', views.LeadgenWebAppOtpRequestView.as_view()),
    url(r'^register/email/otp/validate$', views.LeadgenWebAppOtpValidateView.as_view()),
    # ANA notification
    url(r'^clik-model-notification/$', views.PartnershipClikModelNotificationView.as_view()),
    # Force Fill Partner Application
    # this will cover application with partner referral code or partner onelink
    url(r'^callback-fill-partner-application', views.CallbackFillPartnerApplication.as_view()),
    # Aegis Service
    url(r'^aegis-fdc-inquiry', views.AegisFDCInquiry.as_view()),
]
