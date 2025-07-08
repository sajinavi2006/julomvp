from django.conf.urls import url

from . import views

urlpatterns = [

    url(r'^xls_list$', views.ScrapedDataListView.as_view(),
        name='xls_list'),
    url(r'^sc_xls_detail/(?P<pk>\d+)$', views.ApplicationDetailView.as_view(),
        name='sc_xls_detail'),

]
