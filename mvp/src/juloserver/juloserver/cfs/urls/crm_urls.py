from django.conf.urls import url

from juloserver.cfs.views import crm_views

urlpatterns = [
    url(r'^ajax-app-status-tab/(?P<application_pk>\d+)$', crm_views.ajax_app_status_tab,
        name='ajax_app_status_tab'),
    url(r'^list$', crm_views.AssignmentVerificationDataListView.as_view(), name='list'),
    url(r'^change_pending_state$', crm_views.change_pending_state, name='change_pending_state'),
    url(r'^update_verification_check/(?P<pk>\d+)$', crm_views.update_verification_check,
        name='update_verification_check'),
    url(
        r'^assignment_verification/check_lock_status/(?P<assignment_verification_id>\d+)$',
        crm_views.assignment_verification_check_lock_status,
        name='assignment_verification.check_lock_status'
    ),
    url(
        r'^assignment_verification/lock/(?P<assignment_verification_id>\d+)$',
        crm_views.assignment_verification_lock,
        name='assignment_verification.lock'
    ),
    url(
        r'^assignment_verification/unlock/(?P<assignment_verification_id>\d+)$',
        crm_views.assignment_verification_unlock,
        name='assignment_verification.unlock'
    ),
    url(r'^image_editor/(?P<pk>\d+)$',
        crm_views.ImageDetailView.as_view(), name='image_editor'),
]
