from __future__ import unicode_literals

from django.conf.urls import include, url

from rest_framework import routers

from juloserver.merchant_financing.web_app import views
from juloserver.merchant_financing.web_app.non_onboarding import views as views_non_onboarding

router = routers.DefaultRouter()

urlpatterns = [
    # Root API url: api/merchant-financing/dashboard/
    url(r'^', include(router.urls)),

    # Dashboard Web App API
    url(r'^login', views.LoginDashboardWebApp.as_view(), name="login"),
    url(r'^token/refresh', views.RetriveNewAccessToken.as_view(),
        name='refresh-token'),
    url(r'^logout', views.Logout.as_view(), name='logout'),
    url(r'^profile', views.WebAppDashboardUserProfile.as_view(), name='dashboard-user-profile'),
    url(r'^distributor/upload$', views.UploadDistributorData.as_view(), name="upload-distributor"),
    url(
        r'^distributor/(?P<distributor_id>[0-9]+)$',
        views.DeleteDistributor.as_view(),
        name="distributor",
    ),
    url(r'^distributors$', views.ListDistributorData.as_view(), name="distributors"),
    url(
        r'^applications/(?P<application_id>[0-9]+)/limit',
        views.LimitAdjustmentView.as_view(),
        name="limit-adjustment",
    ),
    url(
        r'^applications/(?P<action>(approve|reject)+$)',
        views.LimitApprovalView.as_view(),
        name="limit-approval"),
    url(r'^applications/(?P<application_id>[0-9]+)$',
        views.ApplicationDetails.as_view(),
        name="applications-details"),
    url(
        r'^applications/(?P<application_type>[a-zA-Z]+)$',
        views.ListApplicationData.as_view(),
        name="applications",
    ),
    # Non-Onboarding session
    url(
        r'^loan/(?P<loan_xid>[0-9]+)/document/upload',
        views_non_onboarding.MFStdNonOnboardingDocumentUploadMfView.as_view(),
        name="non_onboarding_document_upload",
    ),
    url(
        r'^loan/(?P<loan_xid>[0-9]+)/document/submit',
        views_non_onboarding.MFStdNonOnboardingDocumentSubmitMfView.as_view(),
        name="non_onboarding_document_submit",
    ),
    url(
        r'^loan/(?P<loan_xid>[0-9]+)/(?P<file_type>(document|image)+)/(?P<file_id>[0-9]+)$',
        views_non_onboarding.MFStdNonOnboardingGetFileMfView.as_view(),
        name="non_onboarding_get_file",
    ),
    url(
        r'^loan/',
        include(
            'juloserver.merchant_financing.web_app.non_onboarding.urls.api_v1',
            namespace='web_app_non_onboarding',
        ),
    ),
    url(
        r'^loans/(?P<loan_status>(request|approved)+$)',
        views_non_onboarding.DashboardNonOnboardingLoanListView.as_view(),
        name="partner_loan_list",
    ),
    url(
        r'^interest/(?P<loan_xid>[0-9]+)$',
        views_non_onboarding.DashboardInterestListView.as_view(),
        name='dashboard_interest_list',
    ),
    url(
        r'^provision/(?P<loan_xid>[0-9]+)$',
        views_non_onboarding.DashboardProvisionListView.as_view(),
        name='dashboard_provision_list',
    ),
    # V2 MF API Merchant Financing Standard
    url(r'^v2/login', views.LoginDashboardV2WebApp.as_view(), name="login"),
    url(r'^v2/logout', views.LogoutV2.as_view(), name='logout_v2'),
    url(r'^v2/profile', views.WebAppDashboardUserProfileV2.as_view(), name='profile_v2'),
    url(
        r'^merchant/(?P<merchant_status>(in-progress|rejected|approved|document-resubmit|document-required)+)$',
        views.MerchantListData.as_view(),
        name="merchant_list_data",
    ),
    url(
        r'^merchant/(?P<application_xid>[0-9]+)$',
        views.MerchantDetailView.as_view(),
        name='merchant-detail',
    ),
    url(
        r'^merchant/upload/history$',
        views.MerchantUploadHistory.as_view(),
        name='merchant_upload_history',
    ),
    url(
        r'^distributor/upload/pre-check',
        views.UploadDistributorDataPreCheck.as_view(),
        name='distributor_pre_check',
    ),
    url(
        r'^v2/distributor/upload$',
        views.UploadDistributorDataV2.as_view(),
        name="upload-distributor-v2",
    ),
    url(r'^v2/distributors$', views.ListDistributorDataV2.as_view(), name="distributors-v2"),
    url(
        r'^v2/distributor/(?P<distributor_id>[0-9]+)$',
        views.DeleteDistributorV2.as_view(),
        name="distributor-v2",
    ),
    url(r'^merchant/upload$', views.MerchantUploadCsvView.as_view(), name="merchant-upload-csv"),
    url(
        r'^merchant/upload/history/(?P<history_id>[0-9]+)/download',
        views.MerchantDownloadCsvView.as_view(),
        name="merchant-download-csv",
    ),
    url(
        r'^v2/applications/(?P<application_type>(pending|resolved)+)$',
        views.ListApplicationDataV2.as_view(),
        name="applications_v2",
    ),
    url(
        r'^v2/application/(?P<application_id>[0-9]+)/limit',
        views.LimitAdjustmentViewV2.as_view(),
        name="limit-adjustment",
    ),
    url(
        r'^v2/applications/(?P<action_type>(approve|reject)+$)',
        views.ApproveRejectViewV2.as_view(),
        name="approve-reject-v2",
    ),
    url(
        r'^merchant/(?P<application_xid>[0-9]+)/file/upload$',
        views.MerchantUploadFileView.as_view(),
        name="merchant-upload-file",
    ),
    url(
        r'^v2/application/(?P<application_id>[0-9]+)$',
        views.ApplicationDetailViewV2.as_view(),
        name="applications-detail-v2",
    ),
    url(
        r'^application/resubmission/request$',
        views.ReSubmissionApplicationRequestView.as_view(),
        name='resubmission_application_request',
    ),
    # Dashboard Non-Onboarding V2
    url(
        r'^merchant/(?P<application_xid>[0-9]+)/file/submit$',
        views.MerchantSubmitDocumentView.as_view(),
        name='merchant_submit_file',
    ),
    url(
        r'^application/(?P<application_id>[0-9]+)/file/(?P<type>(ktp|ktp-selfie|npwp|nib|agent-with-merchant-selfie|cashflow-report|company-photo)+$)$',
        views.GetApplicationFileByTypeView.as_view(),
        name='get_application_file',
    ),
    url(
        r'^merchant/(?P<application_xid>[0-9]+)/(?P<file_type>(image|document)+)/(?P<file_id>[0-9]+)$',
        views.GetMerchantFileView.as_view(),
        name='get_merchant_file',
    ),
    url(
        r'^application/(?P<application_id>[0-9]+)/(?P<file_type>(image|document)+)/(?P<file_id>[0-9]+)$',
        views.GetApplicationFileView.as_view(),
        name="get_application_file",
    ),
    url(
        r'^application/(?P<application_id>[0-9]+)/risk-assessment$',
        views.ApplicationRiskAssessmentView.as_view(),
        name="application-risk-assessment",
    ),
    url(
        r'^loan/upload/template',
        views_non_onboarding.MFStdNonOnboardingLoanCreationCsvTemplateView.as_view(),
        name="template_loan_creation",
    ),
    url(
        r'^loan/upload/history/(?P<history_id>[0-9]+)/download',
        views_non_onboarding.MFStdNonOnboardingGetLoanUploadHistoryFileView.as_view(),
        name="get_file_loan_upload_history",
    ),
    url(
        r'^loan/upload/history',
        views_non_onboarding.MFStdNonOnboardingLoanUploadHistory.as_view(),
        name="loan_upload_history",
    ),
    url(
        r"^v2/loan/(?P<loan_xid>[0-9]+)",
        views_non_onboarding.MFStdNonOnboardingLoanDetail.as_view(),
        name="loan_detail_v2",
    ),
    url(
        r"v2/loan/upload/submit",
        views_non_onboarding.MFStandardNonOnboardingLoanUploadSubmit.as_view(),
        name="loan_submit_v2",
    ),
    url(
        r"^v2/loan/(?P<loan_status>(draft|need-skrtp|verify|approved|rejected|paid-off)+$)",
        views_non_onboarding.MFStdNonOnboardingLoanList.as_view(),
        name="loan_list_v2",
    ),
]
