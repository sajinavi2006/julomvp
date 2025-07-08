from __future__ import unicode_literals

from django.conf.urls import url

from rest_framework import routers

from juloserver.loan.views import views_api_v1 as views

from juloserver.loan.views import views_rentee
from juloserver.loan.views import views_credit_card
from juloserver.loan.views import views_dbr_v1 as dbr_views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^range-loan-amount/(?P<account_id>[0-9]+)$', views.RangeLoanAmount.as_view()),
    url(r'^loan-purpose/', views.get_julo_one_loan_purpose),
    url(r'^loan-duration', views.LoanCalculation.as_view()),
    url(r'^loan-dbr/get-new-salary/', dbr_views.LoanDbrNewSalary.as_view()),
    url(r'^loan-dbr', dbr_views.LoanDbrCalculation.as_view()),
    url(r'^loan-request-validation/', views.LoanRequestValidation.as_view()),
    url(r'^loan', views.LoanJuloOne.as_view()),
    url(
        r'^agreement/signature/upload/(?P<loan_xid>[0-9]+)/',
        views.LoanUploadSignatureView.as_view(),
    ),
    url(r'^agreement/voice/upload/(?P<loan_xid>[0-9]+)/', views.LoanVoiceUploadView.as_view()),
    url(r'^agreement/loan/(?P<loan_xid>[0-9]+)/', views.LoanAgreementDetailsView.as_view()),
    url(r'^agreement/content/(?P<loan_xid>[0-9]+)/', views.LoanAgreementContentView.as_view()),
    url(r'agreement/loan/status/(?P<loan_xid>[0-9]+)/', views.ChangeLoanStatusView.as_view()),
    url(r'^agreement/voice/script/(?P<loan_xid>[0-9]+)/?$', views.VoiceRecordScriptView.as_view()),
    url(r'^firebase-events/loans/', views.FirebaseEventLoanListView.as_view()),
    url(r'^simulation/range-loan-amount', views.RangeLoanAmountSimulation.as_view()),
    url(r'^simulation/loan-duration', views.LoanDurationSimulation.as_view()),
    # --------rentee loan start----
    url(r'^rentee/loan-duration', views_rentee.RenteeLoanCalculation.as_view()),
    url(r'^rentee/loan-purpose', views_rentee.get_rentee_loan_purpose),
    url(r'^rentee/loan', views_rentee.RenteeLoanJuloOne.as_view()),
    url(r'^rentee/deposit-status/(?P<loan_xid>[0-9]+)/', views_rentee.DepositStatusView.as_view()),
    url(r'^rentee/reactive-loan/(?P<loan_xid>[0-9]+)', views_rentee.RevertLoanView.as_view()),
    url(
        r'^rentee/agreement/content/(?P<loan_xid>[0-9]+)/',
        views_rentee.RenteeLoanSPHPView.as_view(),
    ),
    # --------rentee loan end------

    # --------credit card loan start--------

    url(
        r'^credit-card/loan-duration$',
        views_credit_card.LoanCalculation.as_view()
    ),
    url(
        r'^credit-card/sphp/preview',
        views_credit_card.CreditCardLoanSPHPView.as_view()
    ),
    url(
        r'^credit-card/submit-loan$',
        views_credit_card.SubmitLoan.as_view()
    ),
    url(
        r'^credit-card/loan/(?P<loan_xid>[0-9]+)$',
        views_credit_card.UpdateLoan.as_view()
    ),
    url(
        r'^julo-card/transaction-info/(?P<loan_xid>[0-9]+)$',
        views_credit_card.JuloCardTransactionInfoView.as_view()
    ),
    # --------credit card loan end--------
    url(r'^one-click-repeat', views.OneClickRepeatView.as_view()),
    url(r'^saving-information/duration', views.SavingInformationDuration.as_view()),
    url(r'^zero-interest-popup-banner-content', views.ZeroInterestPopupBanner.as_view()),
    url(r'^user-campaign-eligibility', views.UserCampaignEligibilityView.as_view()),
    url(r'^julo-care/callback', views.JuloCareCallbackView.as_view()),
    url(r'product-list', views.ProductListView.as_view()),
    url(r'^active-platform-rule-check', views.ActivePlatformRuleCheckView.as_view()),
    url(r'^transaction-result/(?P<loan_xid>[0-9]+)', views.TransactionResultView.as_view()),
    url(r'^cross-selling-products', views.CrossSellingProductsView.as_view()),
    url(r'^available-limit-info/(?P<account_id>[0-9]+)', views.AvailableLimitInfoView.as_view()),
    url(r'^locked-product-page', views.LockedProductPageView.as_view()),
]
