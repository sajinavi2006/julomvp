from django.conf.urls import url

from . import views

urlpatterns = [

    # --- role admin full begin ---
    url(r'^image_verification$', views.LoanApplicationView.as_view(
        template_name = 'object/loan_app/admin_full/list_image_verification.html'),
        name='image_verification'),
    url(r'^detail_img_verification/(?P<pk>\d+)$', views.LoanApplicationDetailView.as_view(
        template_name='object/loan_app/admin_full/detail_image_verification.html'),
        name='detail_img_verification'),

    # sphp
    url(r'^sphp$', views.LoanAppSPHPListView.as_view(
        template_name = 'object/loan_app/admin_full/list.html'), name='sphp'),
    url(r'^detail_sphp/(?P<pk>\d+)$', views.LoanApplicationSPHPView.as_view(
        template_name='object/loan_app/admin_full/detail_sphp.html'),
        name='detail_sphp'),
    url(r'^sphp_julo_one/(?P<pk>\d+)$', views.LoanJuloOneSphpDetailView.as_view(
        template_name='object/loan_app/sphp_julo_one.html'),
        name='sphp_julo_one'),
    url(r'^skrtp_julo_one/(?P<pk>\d+)$', views.LoanJuloOneSKRTPDetailView.as_view(
        template_name='object/loan_app/sphp_julo_one.html'),
        name='skrtp_julo_one'),
    url(r'^sphp_grab/(?P<pk>\d+)$', views.LoanGrabSphpDetailView.as_view(
        template_name='object/loan_app/sphp_grab.html'),
        name='sphp_grab'),
    # --- role admin full end ---

    # --- role other then admin begin ---
    url(r'^roles_sphp$', views.LoanAppSPHPListView.as_view(
        template_name = 'object/loan_app/roles/list_sphp.html'), name='roles_sphp'),
    url(r'^roles_detail_sphp/(?P<pk>\d+)$', views.LoanApplicationSPHPView.as_view(
        template_name='object/loan_app/roles/detail_sphp.html'),
        name='roles_detail_sphp'),

    url(r'^roles_image_verification$', views.LoanApplicationView.as_view(
        template_name = 'object/loan_app/roles/list_image_verification.html'),
        name='roles_image_verification'),
    url(r'^roles_detail_img_verification/(?P<pk>\d+)$', views.LoanApplicationDetailView.as_view(
        template_name='object/loan_app/roles/detail_image_verification.html'),
        name='roles_detail_img_verification'),
    url(r'^roles_detail_image_edit/(?P<pk>\d+)$', views.ImageDetailView.as_view(
        template_name='object/loan_app/roles/detail_image_edit.html'),
        name='roles_detail_image_edit'),

    url(r'^roles_detail_img_geohash/(?P<pk>\d+)$', views.LoanApplicationDetailView.as_view(
        template_name='object/loan_app/roles/detail_image_geohash.html'),
        name='roles_detail_img_geohash'),

    url(r'^status_changes$', views.StatusChangesView.as_view(),
        name='status_changes'),
    url(r'^update_app_status/(?P<pk>\d+)$', views.update_app_status,
        name='update_app_status'),
    url(r'^detail_status_changes/(?P<pk>\d+)$', views.StatusChangesDetailView.as_view(),
        name='detail_status_changes'),
    url(r'^create_app_note/(?P<pk>\d+)$', views.create_app_note,
        name='create_app_note'),


    url(r'^list$', views.ApplicationDataListView.as_view(),
        name='list'),
    url(r'^detail_app/(?P<pk>\d+)$', views.ApplicationDetailView.as_view(),
        name='detail_app'),
    # url(r'^detail_app/(?P<pk>\d+/([0-9]+)$', views.ApplicationDetailTabView.as_view(),
    #     name='detail_app'),

    url(r'^verification_cek_list$', views.VerificationCheckListView.as_view(),
        name='verification_cek_list'),
    url(r'^detail_verification_check/(?P<pk>\d+)$', views.VerificationCheckDetailView.as_view(),
        name='detail_verification_check'),
    url(r'^update_verification_check/(?P<pk>\d+)$', views.update_verification_check,
        name='update_verification_check'),

    # --- roles other then admin end ---

    # upload multi image document
    url(r'^app_multi_image_upload/(?P<application_id>\d+)$', views.app_multi_image_upload,
        name='app_multi_image_upload'),


    # upload image document
    url(r'^app_image_upload/(?P<application_id>\d+)$', views.app_image_upload,
        name='app_image_upload'),
    url(r'^detail_image_edit/(?P<pk>\d+)$', views.ImageDetailView.as_view(),
        name='detail_image_edit'),
    # partnership edit image liveness
    url(
        r'^partnership_detail_image_edit/(?P<pk>\d+)/(?P<application_id>\d+)$',
        views.PartnershipLivenessImageDetailView.as_view(),
        name='partnership_detail_image_edit',
    ),
    # --- role admin full end ---


    #for ajax
    url(r'^populate_reason', views.populate_reason, name='populate_reason'),

]
