from django.conf.urls import url

from . import views

urlpatterns = [

    url(r'^list_partial_payment$', views.PartialPaymentListView.as_view(),
        name='list_partial_payment'),
    url(r'^detail_partial_payment/(?P<pk>\d+)$', views.PartialPaymenDetailView.as_view(),
        name='detail_partial_payment'),
]
