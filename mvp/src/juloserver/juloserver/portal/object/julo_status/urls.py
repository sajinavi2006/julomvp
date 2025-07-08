from django.conf.urls import url

from . import views

urlpatterns = [

    # --- role admin full begin ---
    url(r'^status_selections$', views.StatusSelectionsView.as_view(
        template_name = 'object/julo_status/roles/list_status_selections.html'), 
        name='status_selections'),
    url(r'^status_selections_update/(?P<status_code>\d+)$', views.status_selections_update,
        name='status_selections_update'),
    url(r'^detail_status_selection/(?P<pk>\d+)$', views.StatusSelectionDetailView.as_view(),
        name='detail_status_selection'),

    url(r'^reason_selections$', views.ReasonSelectionsView.as_view(
        template_name = 'object/julo_status/roles/list_reason_selections.html'), 
        name='reason_selections'),
    url(r'^reason_selections_update/(?P<status_code>\d+)$', views.reason_selections_update,
        name='reason_selections_update'),
    url(r'^detail_reason_selection/(?P<pk>\d+)$', views.ReasonSelectionDetailView.as_view(),
        name='detail_reason_selection'),

    # --- roles other then admin end ---


]
