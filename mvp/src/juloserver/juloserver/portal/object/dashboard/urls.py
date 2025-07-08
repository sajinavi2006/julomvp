from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^$', views.index, name='default'),
    url(r'^admin_full$', views.dashboard_admin_full, name='admin_full'),
    url(r'^bo_data_verifier$', views.dashboard_bo_data_verifier, name='bo_data_verifier'),
    url(r'^fraudops$', views.dashboard_fraudops, name='fraudops'),
    url(r'^fraudops/geohash_list/$',
        views.dashboard_fraudops_geohash_list,
        name='fraudops_geohash_list'),
    url(r'^bo_credit_analyst$', views.dashboard_bo_credit_analyst, name='bo_credit_analyst'),
    url(r'^bo_sd_verifier$', views.dashboard_bo_sd_verifier, name='bo_sd_verifier'),
    url(r'^bo_general_cs$', views.dashboard_bo_general_cs, name='bo_general_cs'),
    url(r'^autodialer$', views.autodialer, name='autodialer'),
    url(
        r'^collection_supervisor$',
        views.dashboard_collection_supervisor,
        name='collection_supervisor',
    ),
    url(r'^collection_agent_2$', views.dashboard_collection_agent_2, name='collection_agent_2'),
    url(r'^collection_agent_3$', views.dashboard_collection_agent_3, name='collection_agent_3'),
    url(r'^collection_agent_4$', views.dashboard_collection_agent_4, name='collection_agent_4'),
    url(r'^collection_agent_5$', views.dashboard_collection_agent_5, name='collection_agent_5'),
    url(r'^finance$', views.dashboard_finance, name='bo_finance'),
    # bukalapak dashboards
    url(
        r'^collection_agent_partnership_bl_2a$',
        views.collection_agent_partnership_bl_2a,
        name='collection_agent_partnership_bl_2a',
    ),
    url(
        r'^collection_agent_partnership_bl_2b$',
        views.collection_agent_partnership_bl_2b,
        name='collection_agent_partnership_bl_2b',
    ),
    url(
        r'^collection_agent_partnership_bl_3a$',
        views.collection_agent_partnership_bl_3a,
        name='collection_agent_partnership_bl_3a',
    ),
    url(
        r'^collection_agent_partnership_bl_3b$',
        views.collection_agent_partnership_bl_3b,
        name='collection_agent_partnership_bl_3b',
    ),
    url(
        r'^collection_agent_partnership_bl_4$',
        views.collection_agent_partnership_bl_4,
        name='collection_agent_partnership_bl_4',
    ),
    url(
        r'^collection_agent_partnership_bl_5$',
        views.collection_agent_partnership_bl_5,
        name='collection_agent_partnership_bl_5',
    ),
    # new bucket definition
    url(r'^collection_bucket_1$', views.dashboard_collection_bucket_1, name='collection_bucket_1'),
    url(r'^collection_bucket_2$', views.dashboard_collection_bucket_2, name='collection_bucket_2'),
    url(r'^collection_bucket_3$', views.dashboard_collection_bucket_3, name='collection_bucket_3'),
    url(r'^collection_bucket_4$', views.dashboard_collection_bucket_4, name='collection_bucket_4'),
    url(r'^collection_bucket_5$', views.dashboard_collection_bucket_5, name='collection_bucket_5'),
    url(
        r'^collection_bucket_1_non_agent/(?P<role_name>\w+)$',
        views.dashboard_collection_bucket_1_non_agent,
        name='collection_bucket_1_non_agent',
    ),
    url(
        r'^collection_bucket_2_non_agent/(?P<role_name>\w+)$',
        views.dashboard_collection_bucket_2_non_agent,
        name='collection_bucket_2_non_agent',
    ),
    url(
        r'^collection_bucket_3_non_agent/(?P<role_name>\w+)$',
        views.dashboard_collection_bucket_3_non_agent,
        name='collection_bucket_3_non_agent',
    ),
    url(
        r'^collection_bucket_4_non_agent/(?P<role_name>\w+)$',
        views.dashboard_collection_bucket_4_non_agent,
        name='collection_bucket_4_non_agent',
    ),
    url(r'^lender_list_page$', views.LenderListPage.as_view(), name='lender_list_page'),
    url(r'^update_default_role$', views.update_default_role, name='update_default_role'),
    url(r'^update_user_extension$', views.update_user_extension, name='update_user_extension'),
    url(
        r'^ajax_update_user_extension',
        views.ajax_update_user_extension,
        name='ajax_update_user_extension',
    ),
    url(
        r'^ajax_get_application_autodialer',
        views.ajax_get_application_autodialer,
        name='ajax_get_application_autodialer',
    ),
    url(
        r'^get_dashboard_bucket_count',
        views.get_dashboard_bucket_count,
        name='get_dashboard_bucket_count',
    ),
    url(
        r'^get_fraudops_dashboard_bucket_count',
        views.get_fraudops_dashboard_bucket_count,
        name='get_fraudops_dashboard_bucket_count',
    ),
    url(
        r'^get_collection_agent_bucket',
        views.get_collection_agent_bucket,
        name='get_collection_agent_bucket',
    ),
    url(
        r'^get_loc_collection_agent_bucket',
        views.get_loc_collection_agent_bucket,
        name='get_loc_collection_agent_bucket',
    ),
    url(
        r'^get_collection_agent_bl_bucket',
        views.get_collection_agent_bl_bucket,
        name='get_collection_agent_bl_bucket',
    ),
    url(r'^get_script_for_agent', views.get_script_for_agent, name='get_script_for_agent'),
    url(r'^ajax_change_status', views.ajax_change_status, name='ajax_change_status'),
    url(r'^customer_app_action', views.customer_app_action, name='customer_app_action'),
    url(
        r'^ajax_customer_app_action',
        views.ajax_customer_app_action,
        name='ajax_customer_app_action',
    ),
    url(r'^ajax_device_app_action', views.ajax_device_app_action, name='ajax_device_app_action'),
    url(
        r'^ajax_autodialer_session_status',
        views.ajax_autodialer_session_status,
        name='ajax_autodialer_session_status',
    ),
    url(
        r'^ajax_autodialer_agent_status',
        views.ajax_autodialer_agent_status,
        name='ajax_autodialer_agent_status',
    ),
    url(
        r'^ajax_autodialer_history_record',
        views.ajax_autodialer_history_record,
        name='ajax_autodialer_history_record',
    ),
    url(
        r'^ajax_payment_list_collection_agent_view',
        views.ajax_payment_list_collection_agent_view,
        name='ajax_payment_list_collection_agent_view',
    ),
    url(
        r'^ajax_unlock_autodialer_agent',
        views.ajax_unlock_autodialer_agent,
        name='ajax_unlock_autodialer_agent',
    ),
    url(r'^ajax_store_crm_navlog', views.ajax_store_crm_navlog, name='ajax_store_crm_navlog'),
    url(
        r'^get_collection_supervisor_new_bucket',
        views.get_collection_supervisor_new_bucket,
        name='get_collection_supervisor_new_bucket',
    ),
    url(
        r'^get_collection_supervisor_bucket',
        views.get_collection_supervisor_bucket,
        name='get_collection_supervisor_bucket',
    ),
    url(
        r'^get_collection_bucket_v2',
        views.get_collection_bucket_v2,
        name='get_collection_bucket_v2',
    ),
    url(
        r'^ajax_payment_list_collection_supervisor_view',
        views.ajax_payment_list_collection_supervisor_view,
        name='ajax_payment_list_collection_supervisor_view',
    ),
    url(
        r'^get_pv_3rd_party_bucket_count',
        views.get_pv_3rd_party_bucket_count,
        name='get_pv_3rd_party_bucket_count',
    ),
    url(
        r'^activity_dialer_upload/$',
        views.dashboard_activity_dialer_upload,
        name='activity_dialer_upload',
    ),
    url(r'^ops_team_leader/$', views.dashboard_ops_team_leader, name='ops_team_leader'),
    url(
        r'^ajax_ops_team_leader_get_agent',
        views.ajax_ops_team_leader_get_agent,
        name='ajax_ops_team_leader_get_agent',
    ),
    url(
        r'^change_of_repayment_channel$',
        views.dashboard_change_of_repayment_channel,
        name='change_of_repayment_channel',
    ),
    url(
        r'^get_repaymet_channel_details',
        views.get_repaymet_channel_details,
        name='get_repaymet_channel_details',
    ),
    url(
        r'^get_available_repaymet_channel_for_account',
        views.get_available_repaymet_channel_for_account,
        name='get_available_repaymet_channel_for_account',
    ),
    url(
        r'^change_of_payment_visibility$',
        views.dashboard_change_of_payment_visibility,
        name='change_of_payment_visibility',
    ),
    url(
        r'^get_payment_visibility_details',
        views.get_payment_visibility_details,
        name='get_payments_visibility',
    ),
    url(
        r'^update_payments_visibility',
        views.update_payments_visibility,
        name='update_payments_visibility',
    ),
    url(r'^cs_admin_dashboard/$', views.dashboard_cs_admin, name='cs_admin_dashboard'),
    # front end modifier VA
    url(r'^va_modifier/$', views.dashboard_va_modifier, name='va_modifier'),
    url(
        r'^ajax_get_repayment_channels',
        views.ajax_get_repayment_channels,
        name='ajax_get_repayment_channels',
    ),
    url(
        r'^ajax_activate_backup_repayment_channel',
        views.ajax_activate_backup_repayment_channel,
        name='ajax_activate_backup_repayment_channel',
    ),
    url(
        r'^get_repayment_channel_details_axiata',
        views.get_repayment_channel_details_axiata,
        name='get_repayment_channel_details_axiata',
    ),
    url(
        r'^all_collection_dashboard/(?P<role_name>\w+)$',
        views.all_collection_dashboard,
        name='all_collection_dashboard',
    ),
    url(
        r'^j1_agent_assisted_100',
        views.dashboard_j1_agent_assisted_100,
        name='j1_agent_assisted_100',
    ),
    url(r'^collection_field_agent/$', views.dashboard_agent_field, name='collection_field_agent'),
    url(
        r'^bo_outbound_caller_3rd_party',
        views.dashboard_bo_outbound_caller_3rd_party,
        name='bo_outbound_caller_3rd_party',
    ),
]
