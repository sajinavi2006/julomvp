from django.conf.urls import url

from juloserver.channeling_loan.views import crm_views

urlpatterns = [
    url(
        r'^(?P<channeling_type>[A-Za-z0-9]+)/list$',
        crm_views.ChannelingLoanListView.as_view(), name='list'
    ),
    url(
        r'^(?P<channeling_type>[A-Za-z0-9]+)/approval/download$',
        crm_views.download_approval_channeling_loan_data,
        name='download_approval',
    ),
    url(
        r'^(?P<channeling_type>[A-Za-z0-9]+)/download/(?P<file_type>[A-Za-z0-9]+)$',
        crm_views.download_channeling_loan_data, name='download'
    ),
    url(
        r'^(?P<channeling_type>[A-Za-z0-9]+)/upload$',
        crm_views.sync_disbursement_channeling_loan_data,
        name='sync_disbursement',
    ),
    url(
        r'^(?P<channeling_type>[A-Za-z0-9]+)/repayment$',
        crm_views.repayment_channeling_loan_data,
        name='upload_repayment',
    ),
    url(
        r'^(?P<channeling_type>[A-Za-z0-9]+)/reconciliation$',
        crm_views.reconciliation_channeling_loan_data,
        name='upload_reconciliation',
    ),
    url(
        r'^PERMATA/early_payoff/send$',
        crm_views.send_permata_early_payoff_request,
        name='send_permata_early_payoff_request',
    ),
    url(r'^ar_switching$', crm_views.ar_switching_view, name='ar_switching'),
    url(r'^write_off$', crm_views.write_off_view, name='write_off'),
    url(
        r'^lender_osp_transaction_list/$',
        crm_views.LenderOspTransactionListView.as_view(), name='lender_osp_transaction_list',
    ),
    url(
        r'^lender_osp_transaction_create/$',
        crm_views.lender_osp_transaction_create_view, name='lender_osp_transaction_create'
    ),
    url(
        r'^lender_osp_transaction_detail/(?P<lender_osp_transaction_id>\d+)$',
        crm_views.LenderOspTransactionDetailView.as_view(),
        name='lender_osp_transaction_detail',
    ),
    url(
        r'^lender_repayment_list/$',
        crm_views.LenderRepaymentListView.as_view(), name='lender_repayment_list',
    ),
    url(
        r'^lender_repayment_create/$',
        crm_views.lender_repayment_create_view, name='lender_repayment_create'
    ),
    url(
        r'^lender_repayment_detail/(?P<lender_osp_transaction_id>\d+)$',
        crm_views.LenderRepaymentDetailView.as_view(),
        name='lender_repayment_detail',
    ),
    url(
        r'^lender_osp_account_list/$',
        crm_views.LenderOpsAccountListView.as_view(), name='lender_osp_account_list',
    ),
    url(
        r'^lender_osp_account_edit/(?P<lender_osp_account_id>\d+)$',
        crm_views.LenderOpsAccountDetailView.as_view(), name='lender_osp_account_edit'
    ),
]
