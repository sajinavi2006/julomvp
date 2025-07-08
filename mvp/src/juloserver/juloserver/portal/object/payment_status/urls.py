from django.conf.urls import url

from . import views

urlpatterns = [

    url(r'^(?P<status_code>\w+)/list$', views.PaymentDataListView.as_view(),
        name='list'),
    url(r'^change_status/(?P<pk>\d+)$', views.change_pmt_status,
        name='change_status'),
    url(r'^(?P<status_code>\w+)/list_v2$', views.payment_list_view_v2,
        name='list_v2'),
    url(r'^manual_payment_bulk_update', views.manual_payment_bulk_update, name='manual_payment_bulk_update'),

    # for ajax
    url(r'^set_payment_called', views.set_payment_called, name='set_payment_called'),
    url(r'^check_payment_locked', views.check_payment_locked, name='check_payment_locked'),
    url(r'^set_payment_locked', views.set_payment_locked, name='set_payment_locked'),
    url(r'^set_payment_unlocked', views.set_payment_unlocked, name='set_payment_unlocked'),
    url(r'^add_payment_event', views.add_payment_event, name='add_payment_event'),
    url(r'^populate_reason', views.populate_reason, name='populate_reason'),
    url(r'^send_sms', views.send_sms, name='send_sms'),
    url(r'^send_email', views.send_email, name='send_email'),
    url(r'^add_skiptrace', views.add_skiptrace, name='add_skiptrace'),
    url(r'^update_skiptrace', views.update_skiptrace, name='update_skiptrace'),
    url(r'^skiptrace_history', views.skiptrace_history, name='skiptrace_history'),
    url(r'^load_call_result', views.load_call_result, name='load_call_result'),
    url(r'^get_doku_customer_balance', views.get_doku_customer_balance, name='get_doku_customer_balance'),
    url(r'^autodebit_payment_from_doku', views.autodebit_payment_from_doku, name='autodebit_payment_from_doku'),
    url(r'^ajax_update_agent', views.ajax_update_agent, name='ajax_update_agent'),
    url(r'^update_robocall', views.update_robocall, name='update_robocall'),
    url(r'^julo_one_update_robocall', views.julo_one_update_robocall, name='julo_one_update_robocall'),
    url(r'^ajax_payment_list_view', views.ajax_payment_list_view, name='ajax_payment_list_view'),
    url(r'^ajax_cashback_event', views.ajax_cashback_event, name='ajax_cashback_event'),
    url(r'^ajax_update_reminder_call_date', views.ajax_update_reminder_call_date, name='ajax_update_reminder_call_date'),
    url(r'^ajax_change_due_dates', views.ajax_change_due_dates, name='ajax_change_due_dates'),
    url(r'^set_payment_reminder', views.set_payment_reminder, name='set_payment_reminder'),
    url(r'^ajax_reversal_payment_event', views.ajax_reversal_payment_event, name='ajax_reversal_payment_event'),
    url(r'^ajax_set_ignore_calls', views.ajax_set_ignore_calls, name='ajax_set_ignore_calls'),
    url(r'^ajax_change_due_date_init', views.ajax_change_due_date_init, name='ajax_change_due_date_init'),
    url(r'^ajax_set_payment_whatsapp', views.ajax_set_payment_whatsapp, name='ajax_set_payment_whatsapp'),
    url(r'^ajax_save_whatsapp', views.ajax_save_whatsapp, name='ajax_save_whatsapp'),
    url(r'^ajax_change_first_settlement', views.ajax_change_first_settlement, name='ajax_change_first_settlement'),
    url(r'^get_remaining_late_fee_amount', views.get_remaining_late_fee_amount, name='get_remaining_late_fee_amount'),
    url(r'^ajax_get_remaining_amount', views.ajax_get_remaining_amount, name='ajax_get_remaining_amount'),
    url(r'^reversal_payment_event_check_destination', views.reversal_payment_event_check_destination,
        name='reversal_payment_event_check_destination'),
    url(r'^update_payment_note_for_collection', views.update_payment_note_for_collection,
        name='update_payment_note_for_collection')
]
