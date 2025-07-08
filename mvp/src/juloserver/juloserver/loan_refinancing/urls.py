from __future__ import unicode_literals

from django.conf.urls import include, url

from rest_framework import routers

from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^login/(?P<encrypted_customer_data>\w+)/$', views.RefinancingEligibility.as_view()),
    url(r"^get_refinancing_reasons/("
        "?P<encrypted_customer_data>\w+)/$", views.RefinancingReason.as_view()),
    url(r'^get_refinancing_offer/(?P<encrypted_customer_data>\w+)/$',
        views.RefinancingOffer.as_view()),
    url(r'^accept_refinancing_offer/', views.RefinancingOffer.as_view()),
    url(r'^upload_covid_refinancing/', views.CovidRefinancing.as_view()),
    url(r'^covid_refinancing_web_portal/$',
        views.covid_refinancing_web_portal_for_agent, name='covid_refinancing_web_portal'),
    url(r'^ajax_covid_refinancing_calculate_offer_simulation/$',
        views.ajax_covid_refinancing_calculate_offer_simulation,
        name='ajax_covid_refinancing_calculate_offer_simulation'),
    url(r'^ajax_covid_refinancing_submit_waiver_request/$',
        views.ajax_covid_refinancing_submit_waiver_request,
        name='ajax_covid_refinancing_submit_waiver_request'),
    url(r'^covid_approval/(?P<encrypted_uuid>.*)/$', views.covid_approval, name="covid_approval"),
    url(r'^refinancing_form_submit/(?P<encrypted_uuid>.*)/$', views.refinancing_form_submit),
    url(r'^automate_refinancing_offer/(?P<encrypted_uuid>.*)/$',
        views.automate_refinancing_offer, name="automate_offer"),
    url(r'^ajax_get_covid_new_employment_statuses$',
        views.ajax_get_covid_new_employment_statuses,
        name='ajax_get_covid_new_employment_statuses'),
    url(r'^ajax_check_refinancing_request_status',
        views.ajax_check_refinancing_request_status,
        name='ajax_check_refinancing_request_status'),
    url(r'^refinancing_offer_approve/(?P<encrypted_uuid>.*)/$', views.refinancing_offer_approve),
    url(r'^ajax_covid_refinancing_submit_refinancing_request/$',
        views.ajax_covid_refinancing_submit_refinancing_request,
        name='ajax_covid_refinancing_submit_refinancing_request'),
    url(r'^ajax_generate_reactive_refinancing_offer/$',
        views.ajax_generate_reactive_refinancing_offer,
        name='ajax_generate_reactive_refinancing_offer'),
    # submit mobile phone number and request otp
    url(r'^eligibility_check/$', views.EligibilityCheckView.as_view()),
    url(r'^otp_confirmation/$', views.OtpConfirmationView.as_view()),
    url(r'^ajax_get_exisiting_offers',
        views.ajax_get_exisiting_offers,
        name='ajax_get_exisiting_offers'),
    url(r'^ajax_retrigger_comms',
        views.ajax_retrigger_comms,
        name='ajax_retrigger_comms'),
    url(r'^ajax_covid_refinancing_waiver_recommendation/',
        views.ajax_covid_refinancing_waiver_recommendation,
        name='ajax_covid_refinancing_waiver_recommendation',
    ),
    url(r'^submit_waiver_approval', views.submit_waiver_approval, name='submit_waiver_approval'),
    url(
        r'^countdown_time/(?P<encrypted_uuid>.*)/$',
        views.countdown_time_image,
        name="countdown_time",
    ),
]
