from django.conf.urls import url
from . import views

urlpatterns = [
    url(
        r'^ajax_generate_j1_reactive_refinancing_offer/$',
        views.ajax_generate_j1_reactive_refinancing_offer,
        name='ajax_generate_j1_reactive_refinancing_offer',
    ),
    url(
        r'^ajax_simulation_j1_refinancing_calculate_offer/$',
        views.ajax_simulation_j1_refinancing_calculate_offer,
        name='ajax_simulation_j1_refinancing_calculate_offer',
    ),
    url(
        r'^ajax_submit_j1_refinancing_request/$',
        views.ajax_submit_j1_refinancing_request,
        name='ajax_submit_j1_refinancing_request',
    ),
    url(
        r'^ajax_approve_j1_refinancing_request/$',
        views.ajax_approve_j1_refinancing_request,
        name='ajax_approve_j1_refinancing_request',
    ),
    url(
        r'^ajax_retrigger_j1_comms/$', views.ajax_retrigger_j1_comms, name='ajax_retrigger_j1_comms'
    ),
    url(r'^upload_j1_proactive_refinancing/', views.J1ProactiveRefinancing.as_view()),
]
