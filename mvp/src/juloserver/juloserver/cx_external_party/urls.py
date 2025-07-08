from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^info/', views.ExternalDetailAPIView.as_view()),
    url(r'^user-token/', views.GenerateUserToken.as_view()),
    url(r'^user-detail/', views.UserExternalDetailAPIView.as_view()),
    url(r'^customer-info/', views.CustomerInfoView.as_view()),
    url(r'^security-info/', views.SecurityInfoView.as_view()),
    url(r'^app-document-verify-info/', views.AppDocumentVerifyView.as_view()),
    url(r'^user-status-histories/', views.UserStatusHistoryView.as_view()),
    url(r'^customer-personal-data/', views.CustomerPersonalDataView.as_view()),
    url(r'^loan-data/', views.CustomerLoanDataView.as_view()),
    url(r'^account-payment-data/', views.AccountPaymentDataView.as_view()),
    url(r'^customer-loan-payment/', views.CustomerLoanPaymentView.as_view()),
    url(r'^user-application-status/', views.UserApplicationStatusView.as_view()),
]
