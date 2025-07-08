from django.conf.urls import url
from rest_framework import routers

from juloserver.partnership.leadgenb2b.non_onboarding import views

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'products',
        views.LeadgenProductListView.as_view(),
        name="leadgen_product_list",
    ),
    url(
        r'max-platform-check',
        views.LeadgenMaxPlatformCheck.as_view(),
        name="leadgen_max_platform_check",
    ),
    url(
        r'dbr-check',
        views.LeadgenDbrCheck.as_view(),
        name="leadgen_dbr_check",
    ),
    url(r'loan/purposes', views.LoanPurposes.as_view(), name="loan_purposes"),
    url(
        r'loan/bank-account-destination',
        views.LeadgenBankAccountDestination.as_view(),
        name="loan_bank_account_destination",
    ),
    url(
        r'loan/(?P<loan_xid>[0-9]+)/agreement/sign',
        views.LeadgenLoanUploadSignature.as_view(),
        name="loan_agreement_upload_signature",
    ),
    url(
        r'loan/calculate',
        views.LeadgenLoanCalculation.as_view(),
        name="loan_calculation",
    ),
    url(
        r'loan/(?P<loan_xid>[0-9]+)/cancel',
        views.LeadgenLoanCancellation.as_view(),
        name="loan_cancellation",
    ),
    url(
        r"account/account-payment/active$",
        views.LeadgenActiveAccountPayment.as_view(),
        name="account_payment_active",
    ),
    url(
        r'loan/(?P<loan_xid>[0-9]+)/agreement',
        views.LeadgenLoanAgreementContentView.as_view(),
        name="loan_agreement_content",
    ),
    url(
        r'loan/(?P<loan_xid>[0-9]+)/result',
        views.LeadgenLoanTransactionResult.as_view(),
        name="loan_transaction_result",
    ),
    url(
        r'loan/(?P<loan_xid>[0-9]+)',
        views.LeadgenLoanDetail.as_view(),
        name="leadgen_loan_detail",
    ),
    url(
        r'^loans/(?P<action>(active|paid-off)+$)',
        views.LeadgenLoanList.as_view(),
        name="leadgen_loan_list",
    ),
    url(r'loan/inactive$', views.LeadgenInactiveLoan.as_view(), name="inactive_loan"),
    url(
        r'account/account-payment/(?P<account_payment_id>[0-9]+)/(?P<payment_id>[0-9]+)',
        views.LeadgenPaymentDetail.as_view(),
        name="leadgen_payment_detail",
    ),
    url(
        r"account/account-payment/(?P<account_payment_id>[0-9]+)",
        views.LeadgenAccountPaymentDetail.as_view(),
        name="account_payment_detail",
    ),
    url(
        r"account/account-payment$",
        views.LeadgenAccountPaymentList.as_view(),
        name="account_payment_list",
    ),
    url(
        r"payment-method/primary$",
        views.LeadgenGetPrimaryPaymentMethod.as_view(),
        name="get_primary_payment_method",
    ),
    url(
        r'payment-method/primary/(?P<payment_method_id>[0-9]+)$',
        views.LeadgenSetPrimaryPaymentMethod.as_view(),
        name="set_primary_payment_method",
    ),
    url(
        r"payment-methods$",
        views.LeadgenPaymentMethodList.as_view(),
        name="payment_method_list",
    ),
    url(r'loan/$', views.LeadgenLoanCreation.as_view(), name="loan_creation"),
    url(
        r"register/digisign$",
        views.LeadgenRegisterDigisign.as_view(),
        name="register_digisign",
    ),
]
