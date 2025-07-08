from __future__ import unicode_literals
from __future__ import absolute_import

from django.conf.urls import include, url

from rest_framework import routers

from juloserver.followthemoney.views import application_views
from juloserver.followthemoney.withdraw_view import views as withdraw_view

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^login/', application_views.LoginViews.as_view(), name='lender_login'),
    url(r'^register_lender/', application_views.RegisterLenderViews.as_view(), name='register_lender'),
    url(r'^change_password/', application_views.ChangePasswordViews.as_view(), name='lender_change_password'),
    url(r'^check_token/', application_views.CheckTokenLinkViews.as_view()),
    url(r'^forgot_password/', application_views.ForgotPasswordViews.as_view(), name='lender_forgot_password'),
    url(r'^list_bucket/', application_views.ListLenderBucketViews.as_view(), name='list_lender_bucket'),
    url(r'^cancel_bucket/', application_views.CancelBucketViews.as_view(), name='cancel_lender_bucket'),
    url(r'^summary/', application_views.SummaryViews.as_view(), name='followthemoney_summary'),
    url(r'^report/', application_views.ReportViews.as_view(), name='followthemoney_report'),
    url(r'^lender_approval/', application_views.LenderApprovalViews.as_view(), name='lender_approvel'),
    url(r'^loan_agreement/', application_views.LoanAgreementViews.as_view(), name='loan_agreement'),
    url(r'^disbursement/', application_views.disbursement, name='followthemoney_disbursement'),
    url(r'^cancel/', application_views.cancel, name='followthemoney_cancel'),
    url(r'^agreement/', application_views.loanAgreement, name='followthemoney_agreement'),
    url(r'^performance_summary/', application_views.PerformanceSummary.as_view(), name='performance_summary'),
    url(r'^history/', application_views.History.as_view()),
    url(r'^available_balance/', application_views.AvailableBalance.as_view(), name='available_balance'),
    url(r'^lla_docs/(?P<application_xid>[0-9]+)', application_views.LoanLenderAgreementViews.as_view()),
    url(r'^withdraw/', withdraw_view.WithdrawViews.as_view()),
    url(r'^bank_account', withdraw_view.BankAccountViews.as_view()),
    url(r'^withdraw_callback/', withdraw_view.LenderWithdrawalCallbackView.as_view()),
    url(r'^register_lender_web/', application_views.RegisterLenderWebViews.as_view(), name='lender_web'),

    # digisign
    url(r'^digisign/document-status/', application_views.FTMDigisignDocumentStatusView.as_view()),
    url(r'^digisign/sign-document/(?P<bucket_id>[0-9]+)', application_views.FTMDigisignSignDocumentView.as_view()),
    url(r'^digisign/signed-document/', application_views.FTMSignedDocumentView.as_view(), name='signed_doc'),
    url(r'^digisign/list-document/', application_views.FTMListDocumentView.as_view(), name='list_document'),
    url(r'^digisign/unsign-applications/', application_views.UnsignApplicationsView.as_view(), name='unsign'),

    # ojk
    url(r'^ojk/submit-form/', application_views.OJKSubmitFormView.as_view(), name='submit-form'),


]
