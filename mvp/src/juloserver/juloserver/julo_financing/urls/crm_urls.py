from django.conf.urls import url
import juloserver.julo_financing.views.crm_views as crm_views

urlpatterns = [
    url(
        r'^verification-status$',
        crm_views.JFinancingVerificationListView.as_view(),
        name='verification_list',
    ),
    url(
        r'^verification-status/(?P<verification_status>[a-zA-Z_]+)$',
        crm_views.JFinancingVerificationStatusListView.as_view(),
        name='verification_status_list',
    ),
    url(
        r'^verification/(?P<pk>\d+)$',
        crm_views.JFinancingVerificationStatusDetailView.as_view(),
        name='verification_detail',
    ),
    url(
        r'^verification/check_lock_status/(?P<verification_id>\d+)$',
        crm_views.check_locking_j_financing_verification_status,
        name='verification_check_lock_status',
    ),
    url(
        r'^verification/lock/(?P<verification_id>\d+)$',
        crm_views.lock_j_financing_verification_status,
        name='verification_lock',
    ),
    url(
        r'^verification/unlock/(?P<verification_id>\d+)$',
        crm_views.unlock_j_financing_verification_status,
        name='verification_unlock',
    ),
    url(
        r'^verification/(?P<verification_id>\d+)/$',
        crm_views.ajax_update_julo_financing_verification,
        name='verification_detail_update',
    ),
]
