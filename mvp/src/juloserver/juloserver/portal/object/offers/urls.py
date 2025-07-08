from django.conf.urls import url

from . import views

urlpatterns = [

    url(r'^list$', views.OfferListView.as_view(),
        name='list'),
    url(r'^details/(?P<pk>\d+)$', views.details,
        name='details'),

    #ajax
    url(r'^ajax_compute_installment', views.ajax_compute_installment, name='ajax_compute_installment'),
    url(r'^simulated_first_installment', views.simulated_first_installment, name='simulated_first_installment'),
    url(r'^ajax_unavailable_due_dates', views.ajax_unavailable_due_dates, name='ajax_unavailable_due_dates'),
    url(r'^ajax_get_unavailable_due_dates_by_application', views.ajax_get_unavailable_due_dates_by_application, name='ajax_get_unavailable_due_dates_by_application'),
    url(r'^ajax_get_unavailable_due_dates_by_payment', views.ajax_get_unavailable_due_dates_by_payment, name='ajax_get_unavailable_due_dates_by_payment'),
]
