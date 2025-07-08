from django.conf.urls import url

from . import views

urlpatterns = [

    url(r'^(?P<bucket>\w+)/list$', views.loc_collection_list,
        name='list'),
    url(r'^(?P<loc_id>\w+)/detail$', views.loc_collection_detail,
        name='detail'),

    # for ajax
    url(r'^ajax_loc_collection_list', views.ajax_loc_collection_list,
        name='ajax_loc_collection_list'),
    url(r'^get_last_statement', views.get_last_statement,
        name='get_last_statement'),
    url(r'^get_statement_summaries', views.get_statement_summaries,
        name='get_statement_summaries'),
    url(r'^get_va_list', views.get_va_list,
        name='get_va_list'),
    url(r'^get_transaction_list', views.get_transaction_list,
        name='get_transaction_list'),
    url(r'^change_status', views.change_status,
        name='change_status'),
    url(r'^add_notes', views.add_notes,
        name='add_notes'),
    url(r'^get_notes', views.get_loc_notes,
        name='get_notes')
]
