from django.conf.urls import url
from rest_framework import routers
from juloserver.merchant_financing.web_portal import views

router = routers.DefaultRouter()

urlpatterns = [
    # Axiata OJK section
    url(r'^register', views.WebPortalRegister.as_view(), name="register"),
    url(r'^logout', views.WebPortalLogout.as_view(), name="logout"),
    url(r'^temporary-application/(?P<axiata_temporary_data_id>[0-9]+)/submit',
        views.AxiataTemporaryDataSubmitView.as_view(),
        name="axiata_temporary_data_submit"
    ),
    url(r'^verify-otp', views.WebPortalVerifyOtp.as_view(), name='web_portal_verify-otp'),
    url(r'^document/(?P<axiata_temporary_data_id>[0-9]+)$',
        views.UploadDocumentData.as_view(),
        name="document-upload"), 
    url(r'^document/(?P<axiata_temporary_data_id>[0-9]+)/(?P<partnership_image_id>[0-9]+)$',
        views.DownloadDocumentData.as_view(),
        name="document-download"), 
    url(r'^create-temporary-application',
        views.AxiataCreateTemporaryDataView.as_view(),
        name="axiata_create_temporary_data"
    ),
    url(r'^otp-request', views.WebPortalOTPRequest.as_view(), name='web_portal_otp_request'),
    url(r'^view-image', views.ShowImage.as_view(), name="show-image"),
    url(r'^agreement/(?P<loan_xid>[0-9]+)/', views.WebPortalAgreement.as_view(), name='loan_agreement'),
    url(r'^agreement/loan/status/(?P<loan_xid>[0-9]+)/', views.WebPortalLoanStatusView.as_view()),
    url(r'^', views.ListApplications.as_view(), name="applications"),
]
