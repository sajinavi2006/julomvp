from django.conf.urls import include, url
from rest_framework import routers

from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    # Register user and create customer and (empty) application
    url(r'^registration/$', views.RegisterUser.as_view()),
    # Login
    url(r'^login/$', views.Login.as_view()),
    url(r'^login2/?$', views.Login2View.as_view()),
    # Re Apply to create new Application
    url(r'^applications/$', views.ApplicationListCreateView.as_view()),
    # Register user and create customer and (empty) application
    url(r'^application/(?P<pk>[0-9]+)/$', views.ApplicationUpdate.as_view()),
    # product submission
    url(r'^submit-product/(?P<application_id>[0-9]+)/$', views.SubmitProduct.as_view()),
    # Document or sphp_is_signed flag
    url(
        r'^submit-document-flag/(?P<application_id>[0-9]+)/$',
        views.SubmitDocumentComplete.as_view(),
    ),
    # update bank application
    url(r'^bank-application/(?P<application_id>[0-9]+)/$', views.BankApplicationCreate.as_view()),
    # Endpoint for reading all ETL statuses for application
    url(r'^etl/status/(?P<application_id>[0-9]+)/$', views.EtlJobStatusListView.as_view()),
    # Endpoint for uploading DSD to anaserver and starting ETL
    url(r'^etl/dsd/$', views.DeviceScrapedDataUpload.as_view()),
    # Endpoint for uploading App Scraped Devices DSD to anaserver and starting ETL
    url(r'^etl/dsd-clcs/$', views.AppScrapedDataOnlyUpload.as_view()),
    # Endpoint for checking should scrape data or not
    url(
        r'^etl/clcs-scraped-checking/(?P<application_id>[0-9]+)$',
        views.AppScrapedChecking.as_view(),
    ),
    # Endpoint for sending gmail authcode to anaserver for scraping and ETL
    url(r'^etl/gmail/auth-code/$', views.GmailAuthTokenGet.as_view()),
    # Endpoint for sending gmail authcode to anaserver for scraping and ETL
    url(r'^etl/gmail/$', views.GmailAuthToken.as_view()),
    # Endpoint for asking the credit score
    url(r'^credit-score/(?P<application_id>[0-9]+)/$', views.CreditScore2View.as_view()),
    # Endpoint for asking the credit score
    url(r'^credit-score2/(?P<application_id>[0-9]+)/$', views.CreditScore2View.as_view()),
    # terms
    url(r'^privacy/$', views.Privacy.as_view()),
    # request OTP
    url(r'^otp/request/$', views.RequestOTP.as_view()),
    url(r'^application/otp/$', views.ApplicationOtpRequest.as_view()),
    url(r'^application/validate-otp/$', views.ApplicationOtpValidation.as_view()),
    url(r'^application/otp-setting$', views.ApplicationOtpSettingView.as_view()),
    # Login with OTP
    url(r'^otp/login/$', views.LoginWithOTP.as_view()),
    # check referral_code
    url(
        r'^referral-check/(?P<application_id>[0-9]+)/(?P<referral_code>.+)$',
        views.CheckReferral.as_view(),
    ),
    # activation eform voucher
    url(
        r'^bri/redeem-eform-voucher/(?P<application_id>[0-9]+)$',
        views.ActivationEformVoucher.as_view(),
    ),
    # get new eform voucher
    url(r'^bri/new-eform-voucher/(?P<application_id>[0-9]+)$', views.getNewEformVoucher.as_view()),
    # Change password after Login with OTP
    url(r'^otp/change-password$', views.OtpChangePassword.as_view()),
    # Scrapping button list
    url(r'^scraping-buttons$', views.ScrapingButtonList.as_view()),
    # Summary Payments endpoints
    url(r'^loans/(?P<loan_id>[0-9]+)/payments-summary/$', views.PaymentSummaryListView.as_view()),
    # register v2
    url(r'^register2/$', views.RegisterV2View.as_view()),
    # SPHP text by Application
    url(r'^sphp/(?P<application_id>[0-9]+)/$', views.SPHPView.as_view()),
    # Check for Customer App Actions endpoint
    url(r'^check-customer-actions$', views.CheckCustomerActions.as_view()),
    # home screen
    url(r'^homescreen/$', views.HomeScreen.as_view()),
    url(r'^homescreen/combined$', views.CombinedHomeScreen.as_view()),
    # Cashback
    url(r'^cashback/balance$', views.CashbackGetBalance.as_view()),
    url(r'^cashback/transactions$', views.CashbackTransaction.as_view()),
    url(r'^cashback/offered-products$', views.SepulsaProductList.as_view()),
    url(r'^cashback/form-info$', views.CashbackFormInfo.as_view()),
    url(r'^cashback/sepulsa$', views.CashbackSepulsa.as_view()),
    url(
        r'^cashback/sepulsa/inquiry/electricity-account$',
        views.CashbackSepulsaInqueryElectricity.as_view(),
    ),
    url(r'^cashback/payment$', views.CashbackPayment.as_view()),
    url(r'^cashback/transfer$', views.CashbackTransfer.as_view()),
    # once android has changed the api url, url cashback/xendit/transfer can be deprecated
    url(r'^cashback/xendit/transfer$', views.CashbackTransfer.as_view()),
    url(r'^cashback/last_bank_info$', views.CashbackLastBankInfo.as_view()),
    url(r'^cashback/bar$', views.CashbackBar.as_view()),
    # status_label
    url(r'^status-label$', views.StatusLabelView.as_view()),
    # reapply
    url(r'^reapply$', views.ApplicationReapplyView.as_view()),
    # Product line endpoints
    url(r'^product-lines$', views.ProductLineListView.as_view()),
    # Collateral dropdown endpoint
    url(r'^collateral/dropdowns$', views.CollateralDropDown.as_view()),
    # update google auth token
    url(r'^google-auth-token-update$', views.UpdateGmailAuthToken.as_view()),
    # Skiptrace list
    url(r'^guarantor-contact$', views.SkiptraceView.as_view()),
    # Chat bot feature toggle
    url(r'^chat-bot$', views.ChatBotSetting.as_view()),
    # Skiptrace guarantor contact settings
    url(r'^guarantor-setting$', views.GuarantorContactSettingView.as_view()),
    # Loan Payment Detail Popup
    url(r'^popup/unpaid-payment-detail$', views.UnpaidPaymentPopupView.as_view()),
    # Facebook data
    url(r'^facebookdata/$', views.FacebookDataView.as_view()),
    # app_version check
    url(r'^version/check$', views.VersionCheckView.as_view()),
    # faq section
    url(r'^faq/$', views.FAQDataView.as_view({"get": "get_all"})),
    url(r'^faq/assist/$', views.FAQDataView.as_view({"get": "get_assist"})),
    url(r'^faq/(?P<section_id>[0-9]+)/$$', views.FAQDataView.as_view({"get": "get"})),
    url(r'^additional/info/$', views.AdditionalInfoView.as_view()),
    # promo hi season
    url(r'^promo/(?P<customer_id>[0-9]+)/$', views.PromoInfoView.as_view()),
    # Digisign url
    url(r'^digisign/register$', views.DigisignRegisterView.as_view()),
    url(r'^digisign/send-document$', views.DigisignSendDocumentView.as_view()),
    url(r'^digisign/activate$', views.DigisignActivateView.as_view()),
    url(
        r'^digisign/sign-document/(?P<application_id>[0-9]+)/$',
        views.DigisignSignDocumentView.as_view(),
    ),
    url(r'^digisign/user-status$', views.DigisignUserStatusView.as_view()),
    url(r'^digisign/user-activation$', views.DigisignUserActivationView.as_view()),
    url(
        r'^digisign/document-status/(?P<application_id>[0-9]+)/$',
        views.DigisignDocumentStatusView.as_view(),
    ),
    url(r'^digisign/failed-action/$', views.DigisignFailedActionView.as_view()),
    url(r'^mobile/feature-settings$', views.MobileFeatureSettingView.as_view()),
    url(
        r'^mobile/check-payslip-mandatory/(?P<application_id>[0-9]+)/$',
        views.CheckPayslipMandatory.as_view(),
    ),
    # url(r'^upload/update-centerix-payment-data', views.UpdateCenterixPaymentData.as_view()),
    url(r'^upload/update-centerix-skiptrace-data', views.UpdateCenterixSkiptraceData.as_view()),
    # popup tutorial sphp digisign
    url(r'^popup/sphp-tutorial$', views.TutorialSphpPopupView.as_view()),
    url(r'^referral-home/(?P<customer_id>[0-9]+)/$', views.ReferralHome.as_view()),
    # user feedback
    url(r'^user-feedback$', views.UserFeedback.as_view()),
    url(r'^change-email/$', views.ChangeEmailView.as_view()),
    url(r'^security-faq/$', views.SecurityFaqApiview.as_view({"get": "get_all"})),
    url(
        r'^security-faq/(?P<section_id>[0-9]+)/$', views.SecurityFaqApiview.as_view({"get": "get"})
    ),
    # Payment info
    url(r'^payment-info/(?P<payment_id>.+)/$', views.PaymentInfoRetrieveViewV2.as_view()),
    url(r'^help-center/$', views.HelpCenterView.as_view({"get": "get_all"})),
    url(r'^help-center/(?P<slug>[\w-]+)/$', views.HelpCenterView.as_view({"get": "get"})),
    url(r'^product-line/(?P<product_line_code>[0-9]+)/dropdown_data$', views.DropDownApi.as_view()),
    url(r'^creation-form-alerts/$', views.FormAlertMessageView.as_view()),
]
