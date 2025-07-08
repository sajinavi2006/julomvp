from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^(?P<status_code>\w+)/list$', views.account_list_view, name='list'),
    url(r'^account_details/(?P<account_id>\d+)$', views.account_details, name='account_details'),
    url(r'^(?P<status_code>\w+)/list$', views.account_list_view, name='list'),
    url(
        r'^ajax_account_status_list_view',
        views.ajax_account_status_list_view,
        name='ajax_account_status_list_view',
    ),
    url(r'^skiptrace_history', views.skiptrace_history, name='skiptrace_history'),
    url(r'^send_sms', views.send_sms, name='send_sms'),
    url(r'^send_email', views.send_email, name='send_email'),
    url(
        r'^loan_paid_letter_ajax',
        views.LoanEligiblePaidLetter.as_view(),
        name='loan_paid_letter_ajax',
    ),
]
