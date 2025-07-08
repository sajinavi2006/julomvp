from django.conf.urls import url
from rest_framework import routers

from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^collection_hi_season_campaign_list/$',
        views.collection_hi_season_campaign_list,
        name='collection_hi_season_campaign_list',
    ),
    url(
        r'^collection_hi_season_campaign_form$',
        views.campaign_form,
        name='collection_hi_season_campaign_form',
    ),
    url(r'^update_campaign_status$', views.update_campaign_status, name='update_campaign_status'),
    url(
        r'^ajax_generate_banner_schedule_hi_season$',
        views.ajax_generate_banner_schedule_hi_season,
        name='ajax_generate_banner_schedule_hi_season',
    ),
    url(
        r'^ajax_generate_comms_setting_schedule_hi_season$',
        views.ajax_generate_comms_setting_schedule_hi_season,
        name='ajax_generate_comms_setting_schedule_hi_season',
    ),
    url(
        r'^ajax_get_partner_list_hi_season$',
        views.ajax_get_partner_list_hi_season,
        name='ajax_get_partner_list_hi_season',
    ),
    url(
        r'^ajax_upload_banner_hi_season$',
        views.ajax_upload_banner_hi_season,
        name='ajax_upload_banner_hi_season',
    ),
    url(
        r'^ajax_delete_comms_setting$',
        views.ajax_delete_comms_setting,
        name='ajax_delete_comms_setting',
    ),
]
