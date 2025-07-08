from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^list$', views.ProductProfileListView.as_view(),
        name='list'),
    url(r'^details/(?P<pk>\d+)$', views.details,
        name='details'),
    url(r'^add/$', views.add,
        name='add'),
    url(r'^ajax_add/', views.ajax_add, name='ajax_add'),
    url(r'^ajax_get_detail/', views.ajax_get_detail, name='ajax_get_detail'),
    url(r'^ajax_update_detail/', views.ajax_update_detail, name='ajax_update_detail')
]
