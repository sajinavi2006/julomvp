from django.conf.urls import url
from rest_framework import routers
from juloserver.partnership import views
from juloserver.partnership.miniform.views import MiniFormPhoneOfferView

router = routers.DefaultRouter()

urlpatterns = [
    # Web API's For Whitelabel
    url(r'^whitelabel-paylater-mobile/feature-settings$',
        views.WhitelabelMobileFeatureSettingView.as_view()),
    url(r'^whitelabel-paylater-application/otp$',
        views.WhitelabelApplicationOtpRequest.as_view()),
    url(r'^whitelabel-paylater-application/email-otp$',
        views.WhitelabelApplicationEmailOtpRequest.as_view()),
    url(r'^whitelabel-paylater-application/validate-otp/$',
        views.WhitelabelApplicationOtpValidation.as_view()),
    url(r'^whitelabel-paylater-application/details/$',
        views.WhitelabelApplicationDetailsView.as_view()),
    url(r'whitelabel-paylater-input-pin/$',
        views.WhitelabelInputPinView.as_view()),
    url(r'whitelabel-paylater-link-account/$',
        views.WhitelabelLinkAccountView.as_view()),
    url(r'^loan$', views.WebviewLoanView.as_view()),

    # Web API's For LinkAJA
    url(r'^request-otp', views.WebviewApplicationOtpRequest.as_view()),
    url(r'^request-email-otp', views.WebviewApplicationEmailOtpRequest.as_view()),
    url(r'^confirm-email-otp', views.WebviewEmailOtpConfirmation.as_view()),
    url(r'^confirm-otp', views.WebviewApplicationOtpConfirmation.as_view()),
    url(r'agreement/loan/status/(?P<loan_xid>[0-9]+)/',
        views.WebviewChangeLoanStatusView.as_view()),

    url(r'^check-partner-strong-pin$', views.WebviewCheckPartnerStrongPin.as_view()),
    url(r'^create-partner-pin$', views.WebviewCreatePartnerPin.as_view()),
    url(r'^verify-partner-pin$', views.WebviewVerifyPartnerPin.as_view()),

    url(r'^dropdowns$', views.WebviewDropdownDataView.as_view()),
    url(r'^address$', views.WebviewAddressLookupView.as_view()),
    url(r'^images$', views.WebviewImageListCreateView.as_view()),
    url(r'^submit$', views.WebviewSubmitApplicationView.as_view()),
    url(r'^get-phone-number$', views.GetPhoneNumberView.as_view()),
    url(r'^register$', views.WebviewRegistration.as_view()),

    url(r'^check-partner-strong-pin$', views.WebviewCheckPartnerStrongPin.as_view()),
    url(r'^create-partner-pin$', views.WebviewCreatePartnerPin.as_view()),
    url(r'^verify-partner-pin$', views.WebviewVerifyPartnerPin.as_view()),
    url(r'^loan-offer$', views.WebviewLoanOfferView.as_view()),
    url(r'^loan-expectation$', views.WebViewLoanExpectationView.as_view()),
    url(r'^check_registered_user$', views.WebviewCheckRegisteredUser.as_view()),
    url(r'^login$', views.WebviewLogin.as_view()),

    url(r'^info-card$', views.WebviewInfocard.as_view()),
    url(r'^application/status$', views.WebviewApplicationStatus.as_view()),
    url(r'^booster/status/(?P<application_id>[0-9]+)/$',
        views.PartnershipBoostStatusView.as_view()),
    url(r'^booster/document-status/(?P<application_id>[0-9]+)/$',
        views.PartnershipBoostStatusAtHomepageView.as_view()),
    url(r'^credit-info', views.PartnershipCreditInfoView.as_view()),
    url(r'^submit-document-flag/(?P<application_id>[0-9]+)/$',
        views.PartnershipSubmitDocumentCompleteView.as_view()),
    url(r'^homescreen/combined$', views.PartnershipCombinedHomeScreen.as_view()),
    url(r'^images/$', views.PartnershipImageListCreateView.as_view()),
    url(r'^applications/(?P<application_id>[0-9]+)/images/$',
        views.PartnershipImageListView.as_view()),
    url(r'^agreement/content/(?P<loan_xid>[0-9]+)/$',
        views.WebviewLoanAgreementContentView.as_view()),
    url(r'^agreement/voice/script/(?P<loan_xid>[0-9]+)/$',
        views.WebviewVoiceRecordScriptView.as_view()),
    url(r'^agreement/voice/upload/(?P<loan_xid>[0-9]+)/',
        views.WebviewLoanVoiceUploadView.as_view()),
    url(r'^agreement/signature/upload/(?P<loan_xid>[0-9]+)/',
        views.WebviewLoanUploadSignatureView.as_view()),
    url(r'^agreement/loan/(?P<loan_xid>[0-9]+)/$',
        views.WebviewLoanAgreementDetailsView.as_view()),
    url(r'^create-pin$', views.WebviewCreatePin.as_view()),
    url(r'^validate-application$', views.ValidateApplicationView.as_view()),
    url(r'^details$', views.PartnerDetailsView.as_view()),

    # calculate loan
    url(r'^calculate-loan', views.PartnerLoanSimulationView.as_view()),

    # leadgen-webview
    url(r'^reset-pin$', views.LeadgenResetPinView.as_view()),
    url(r'^application/(?P<application_id>[0-9]+)/$', views.LeadgenApplicationUpdateView.as_view()),
    url(r'^check-user/$',
        views.PaylaterCheckUserView.as_view()),
    url(r'^paylater-product-details',
        views.PaylaterProductDetailsView.as_view()),
    url(
        r'^whitelabel-paylater-request-email-otp', views.WhitelabelRegisterEmailOtpRequest.as_view()
    ),
    url(r'^whitelabel-paylater-validate-email-otp',
        views.WhitelabelEmailOtpValidation.as_view()),
    url(r'^whitelabel-paylater-register',
        views.WhitelabelRegisteration.as_view()),
    url(r'^paylater-info-card$', views.PaylaterInfoCardView.as_view()),
    url(r'^paylater-homescreen/combined$', views.PaylaterCombinedHomeScreen.as_view()),
    url(r'^paylater-credit-info', views.PaylaterCreditInfoView.as_view()),

    url(r'^skrtp/(?P<b64_string>.+)/sign', views.SignMfSkrtpView.as_view(), name="show-mf-skrtp"),
    url(r'^skrtp/(?P<b64_string>.+)', views.ShowMfSkrtpView.as_view(), name="show-mf-skrtp"),
    url(
        r'^digisign/status/(?P<b64_string>.+)',
        views.PartnershipDigisignStatus.as_view(),
        name="partnership-digisign-status",
    ),

    url(r'^(?P<partner_name>[a-z0-9A-Z_-]+)/pin/(?P<action_type>[a-z]+)$',
        views.SetPinFromLinkView.as_view()),
    url(
        r'^(?P<partner_name>[a-z0-9A-Z_-]+)/application-info',
        views.AgentAssistedApplicationInfo.as_view(),
    ),

    # gojek-tsel
    url(r'mini-form', MiniFormPhoneOfferView.as_view())
]
