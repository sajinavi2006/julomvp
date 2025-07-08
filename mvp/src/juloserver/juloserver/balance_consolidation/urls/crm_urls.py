from django.conf.urls import url
from juloserver.balance_consolidation.views import crm_views

urlpatterns = [
    url(
        r'^details/(?P<pk>\d+)$',
        crm_views.BalanceConsolidationVerificationDetailFormView.as_view(),
        name='balance_consolidation_verification_details',
    ),
    url(
        r'^ajax_bank_validation/',
        crm_views.ajax_bank_validation_consolidation,
        name='ajax_bank_validation',
    ),
    url(
        r'^list$',
        crm_views.BalanceConsolidationVerificationListView.as_view(),
        name='balance_consolidation_verification_list',
    ),
    url(
        r'^ajax_balance_consolidation/(?P<consolidation_verification_id>\d+)$',
        crm_views.ajax_balance_consolidation,
        name='ajax_balance_consolidation'
    ),
    url(
        r'^consolidation_verification/check_lock_status/(?P<consolidation_verification_id>\d+)$',
        crm_views.consolidation_verification_check_lock_status,
        name='consolidation_verification.check_lock_status'
    ),
    url(
        r'^consolidation_verification/lock/(?P<consolidation_verification_id>\d+)$',
        crm_views.consolidation_verification_lock,
        name='consolidation_verification.lock'
    ),
    url(
        r'^consolidation_verification/unlock/(?P<consolidation_verification_id>\d+)$',
        crm_views.consolidation_verification_unlock,
        name='consolidation_verification.unlock'
    ),
    url(r'^verifications/(?P<verification_id>[0-9]+)/$',
        crm_views.update_balance_consolidation_verification,
        name='balance_consolidation_verification_update'
    ),
    url(r'^verifications/(?P<verification_id>[0-9]+)/upload_document$',
        crm_views.upload_document_balance_consolidation_verification,
        name='balance_consolidation_verification_upload_document'
    ),
]
