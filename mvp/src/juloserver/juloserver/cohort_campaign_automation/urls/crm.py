from django.conf.urls import url
from juloserver.cohort_campaign_automation import views


urlpatterns = [
    url(
        r'^list/',
        views.cohort_campaign_automation_list,
        name='cohort_campaign_automation_list',
    ),
    url(
        r'^ajax_cohort_campaign_automation_list_view/',
        views.ajax_cohort_campaign_automation_list_view,
        name='ajax_cohort_campaign_automation_list_view',
    ),
    url(
        r'^create/',
        views.create_cohort_campaign_automation,
        name='create_cohort_campaign_automation',
    ),
    url(
        r'^submit/',
        views.submit_cohort_campaign_automation,
        name='submit_cohort_campaign_automation',
    ),
    url(
        r'^cancel/',
        views.cancel_status_cohort_campaign_automtion,
        name='cancel_status_cohort_campaign_automation',
    ),
    url(
        r'^edit/(?P<campaign_name>\w+)/$',
        views.edit_cohort_campaign_automation,
        name='edit_cohort_campaign_automation',
    ),
]
