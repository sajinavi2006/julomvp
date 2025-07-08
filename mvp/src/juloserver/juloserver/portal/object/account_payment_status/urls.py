from django.conf.urls import url

from . import views

urlpatterns = [

    url(r'^change_status/(?P<pk>\d+)$', views.change_account_payment_status,
        name='change_status'),
    url(r'^(?P<status_code>\w+)/list$', views.account_payment_list_view,
        name='list'),
    url(r'^add_account_transaction', views.add_account_transaction, name='add_account_transaction'),
    url(r'^ajax_reversal_account_payment_event', views.ajax_reversal_account_payment_event, name='ajax_reversal_account_payment_event'),
    url(r'^reversal_payment_event_check_account_destination', views.reversal_payment_event_check_account_destination, name='reversal_payment_event_check_account_destination'),
    url(r'^send_sms', views.send_sms, name='send_sms'),
    url(r'^send_email', views.send_email, name='send_email'),
    url(r'^ajax_reversal_account_payment_event', views.ajax_reversal_account_payment_event, name='ajax_reversal_account_payment_event'),
    url(r'^reversal_payment_event_check_account_destination', views.reversal_payment_event_check_account_destination, name='reversal_payment_event_check_account_destination'),
    url(r'^ajax_account_payment_list_view', views.ajax_account_payment_list_view, name='ajax_account_payment_list_view'),
    url(r'^skiptrace_history', views.skiptrace_history, name='skiptrace_history'),
    url(r'^ajax_change_first_settlement',
        views.ajax_change_first_settlement,
        name='ajax_change_first_settlement',
    ),
    url(
        r'^ajax_check_can_change_paydate',
        views.ajax_check_can_change_paydate,
        name='ajax_check_can_change_paydate',
    ),
    url(
        r'^simulate_adjusted_installment',
        views.simulate_adjusted_installment,
        name='simulate_adjusted_installment',
    ),
    url(r'^account_dashboard/(?P<pk>\d+)$', views.account_dashboard, name='account_dashboard'),
    url(
        r'^ajax_get_skiptrace_history/(?P<application_id>\d+)',
        views.get_skiptrace_history,
        name='ajax_get_skiptrace_history',
    ),
    url(
        r'^ajax_get_mjolnir_call_summary/(?P<application_id>\d+)$',
        views.get_mjolnir_call_summary,
        name='ajax_get_mjolnir_call_summary',
    ),
    url(r'^ajax_get_status_history/(?P<payment_id>\d+)', views.get_status_history,
        name='ajax_get_status_history'),
    url(r'^ajax_get_email_sms_history/(?P<payment_id>\d+)', views.get_email_sms_history,
        name='ajax_get_email_sms_history'),
    url(
        r'^ajax_get_fdc_details/(?P<customer_id>\d+)$',
        views.get_fdc_details,
        name='ajax_get_fdc_details',
    ),
]
