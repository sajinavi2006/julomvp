from django.conf.urls import url
from .. import views

urlpatterns = [
    url(r'^collection-offer-j1/$', views.collection_offer_j1, name='collection-offer-j1'),
    url(r'^ajax_get_j1_exisiting_offers', views.ajax_get_j1_exisiting_offers,
        name='ajax_get_j1_exisiting_offers'),
    url(r'^ajax_generate_j1_waiver_refinancing_offer/$',
        views.ajax_generate_j1_waiver_refinancing_offer,
        name='ajax_generate_j1_waiver_refinancing_offer'),
    url(r'^ajax_j1_waiver_recommendation/', views.ajax_j1_waiver_recommendation,
        name='ajax_j1_waiver_recommendation'),
    url(
        r'^ajax_j1_covid_refinancing_submit_waiver_request/$',
        views.ajax_j1_covid_refinancing_submit_waiver_request,
        name='ajax_j1_covid_refinancing_submit_waiver_request',
    ),
    url(
        r'^submit_j1_waiver_approval',
        views.submit_j1_waiver_approval,
        name='submit_j1_waiver_approval',
    ),
    url(
        r'^manual_waiver_expiry_page/$',
        views.manual_waiver_expiry_page,
        name='manual_waiver_expiry_page',
    ),
    url(
        r'^submit_manual_waiver_expiry/$',
        views.submit_manual_waiver_expiry,
        name='submit_manual_waiver_expiry',
    ),
    url(r'^fc_agents_list/', views.fc_agents_list, name='fc_agents_list'),
]
