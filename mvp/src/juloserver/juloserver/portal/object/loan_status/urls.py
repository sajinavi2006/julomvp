from django.conf.urls import url

from . import views

urlpatterns = [

    url(r'^(?P<status_code>\w+)/list$', views.LoanDataListView.as_view(),
        name='list'),
    url(r'^(?P<status_code>\w+)/app_status/(?P<app_status>\w+)/list$', views.LoanDataListView.as_view(),
        name='sublist'),
    url(r'^details/(?P<pk>\d+)$', views.details,
        name='details'),

    # for ajax
    url(r'^simulate_adjusted_installment', views.simulate_adjusted_installment,
        name='simulate_adjusted_installment'),
    url(r'^ajax_unavailable_due_dates', views.ajax_unavailable_due_dates,
        name='ajax_unavailable_due_dates'),
    url(r'^ajax_bulk_vendor_reassign', views.ajax_bulk_vendor_reassign,
        name='ajax_bulk_vendor_reassign'),
    url(r'^ajax_update_ptp', views.ajax_update_ptp, name='ajax_update_ptp'),
    # Vendor reassign from Loan Details page
    url(r'^ajax_vendor_reassign', views.ajax_vendor_reassign, name='ajax_vendor_reassign'),
    # mar loan restructure
    url(r'^ajax_mark_loan_restructure', views.ajax_mark_loan_restructure,
        name='ajax_mark_loan_restructure'),

    #for bulk loan reassignemnt
    url(r'^bulk_loan_reassignment', views.bulk_loan_reassignment, name='bulk_loan_reassignment'),
    url(r'^ajax_bulk_loan_reassignment_get_data', views.ajax_bulk_loan_reassignment_get_data, name='ajax_bulk_loan_reassignment_get_data'),
    url(r'^ajax_loan_reassignment', views.ajax_loan_reassignment, name='ajax_loan_reassignment'),

    url(r'^ajax_squad_reassignment', views.ajax_squad_reassignment, name='ajax_squad_reassignment'),
]
