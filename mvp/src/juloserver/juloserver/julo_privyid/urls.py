from django.conf.urls import include, url
from rest_framework import routers


from . import views
router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^feature-status/$', views.PrivyFeatureStatus.as_view()),
    url(r'^customer-status/$', views.PrivyCustomerStatus.as_view()),
    url(r'^document-upload/$', views.PrivyDocumentUpload.as_view()),
    url(r'^document-status/$', views.PrivyDocumentStatus.as_view()),
    url(r'^request-otp/$', views.PrivyRequestOtp.as_view()),
    url(r'^confirm-otp/$', views.PrivyConfirmOtp.as_view()),
    url(r'^document-sign/$', views.PrivySignDocument.as_view()),

    # Julo One Refactor
    url(r'^customer-status-privy/$', views.PrivyCustomerStatusView.as_view()),
    url(r'^document-upload-privy/$', views.PrivyDocumentUploadView.as_view()),
    url(r'^document-status-privy/(?P<loan_xid>[0-9]+)/$', views.PrivyDocumentStatusView.as_view()),
    url(r'^request-otp-privy/$', views.PrivyRequestOtpView.as_view()),
    url(r'^confirm-otp-privy/$', views.PrivyConfirmOtpView.as_view()),
    url(r'^document-sign-privy/$', views.PrivySignDocumentView.as_view()),

    # Reupload Images
    url(r'^upload-image-reupload/(?P<image_type>[a-z0-9A-Z_-]+)/$', views.ReuploadPrivyImage.as_view()),
    url(r'^reupload-privy-customer/$', views.PrivyReRegisterView.as_view()),
]
