from django.conf.urls import url

from juloserver.customer_module.views import crm_v1 as crm_views

urlpatterns = [
    url(r'^customer-removal/$', crm_views.CustomerRemovalView.as_view(), name='customer_removal'),
    url(r'^search-customer/$', crm_views.SearchCustomer.as_view(), name='search_customer'),
    url(r'^delete-customer/$', crm_views.DeleteCustomerView.as_view(), name='delete_customer'),
    url(r'^manual-deletion/$', crm_views.dashboard_account_deletion_manual, name='manual-deletion'),
    url(
        r'^get-customer-delete-updated-data/$',
        crm_views.GetCustomerDeleteUpdatedData.as_view(),
        name='get_deleted_update_data',
    ),
    url(
        r'^deletion-request-inapp/$',
        crm_views.dashboard_account_deletion_julo_app,
        name='deletion-request-inapp',
    ),
    url(
        r'^in-app-deletion-request/$',
        crm_views.AccountDeleteMenuInApp.as_view(),
        name='in-app-deletion-request',
    ),
    url(
        r'^in-app-deletion-update-status/$',
        crm_views.UpdateStatusOfAccountDeletionRequest.as_view(),
        name='in-app-deletion-request',
    ),
    url(
        r'^in-app-deletion-request-history/$',
        crm_views.AccountDeleteMenuInAppHistory.as_view(),
        name='in-app-deletion-request-history',
    ),
    url(
        r'^customer-data/change-request/$',
        crm_views.CustomerDataChangeRequestListView.as_view(),
        name='customer_data.list',
    ),
    url(
        r'^customer-data/change-request/(?P<pk>[0-9]+)/$',
        crm_views.CustomerDataChangeRequestDetailView.as_view(),
        name='customer_data.detail',
    ),
    url(
        r'^customer-data/change-request/customer-info/(?P<customer_id>[0-9]+)/$',
        crm_views.CustomerDataChangeRequestCustomerInfoView.as_view(),
        name='customer_data.customer-info',
    ),
    url(
        r'^customer-data/dashboard/$',
        crm_views.CustomerDataChangeRequestDashboardView.as_view(),
        name='customer_data.dashboard',
    ),
    url(
        r'^account-deletion-histories/$',
        crm_views.dashboard_account_deletion_history,
        name='account-deletion-history',
    ),
    url(
        r'^account-deletion-histories/search/$',
        crm_views.SearchAccountDeletionHistory.as_view(),
        name='search-acccount-deletion-history',
    ),
    url(
        r'^consent-withdrawal/$', crm_views.dashboard_consent_withdrawal, name='consent_withdrawal'
    ),
    url(
        r'^consent-withdrawal/histories/$',
        crm_views.ConsentWithdrawalHistoryView.as_view(),
        name='consent-withdrawal-history',
    ),
    url(r'consent-withdrawal/crm/request/$', crm_views.ConsentWithdrawalRequestView.as_view()),
    url(
        r'consent-withdrawal/crm/change-status/(?P<action>[a-zA-Z_]+)$',
        crm_views.ChangeStatusConsentWithdrawalView.as_view(),
    ),
    url(
        r'^consent-withdrawal/list-request/',
        crm_views.ConsentWithdrawalListRequestView.as_view(),
        name='consent-withdrawal-list-request',
    ),
]
