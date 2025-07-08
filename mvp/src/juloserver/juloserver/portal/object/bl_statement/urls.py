from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^(?P<status_code>\w+)/list$', views.statement_list_view, name='list'),
    url(r'^detail/(?P<pk>\d+)$', views.statement_detail, name='detail'),

    #for ajax
    url(r'^ajax_statement_list_view', views.ajax_statement_list_view, name='ajax_statement_list_view'),
    url(r'^ajax_lock_statement', views.ajax_lock_statement, name='ajax_lock_statement'),
    url(r'^ajax_unlock_statement', views.ajax_unlock_statement, name='ajax_unlock_statement'),
    url(r'^ajax_create_statement_note', views.ajax_create_statement_note, name='ajax_create_statement_note'),
    url(r'^ajax_add_skiptrace', views.add_skiptrace, name='ajax_add_skiptrace'),
    url(r'^ajax_create_skiptrace_history', views.create_skiptrace_history, name='ajax_create_skiptrace_history'),
    url(r'^ajax_update_skiptrace', views.update_skiptrace, name='ajax_update_skiptrace'),
    url(r'^ajax_update_ptp', views.ajax_update_ptp, name='ajax_update_ptp'),
    url(r'^ajax_statement_set_called', views.ajax_statement_set_called, name='ajax_statement_set_called'),
    url(r'^ajax_add_statement_event', views.ajax_add_statement_event, name='ajax_add_statement_event'),
    url(r'^ajax_create_va_and_send_sms', views.ajax_create_va_and_send_sms, name='ajax_create_va_and_send_sms'),
]
