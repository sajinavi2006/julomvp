from django.conf.urls import url
from rest_framework import routers

from juloserver.customer_module.urls import crm_v1
from juloserver.customer_module.views import views_api_v1 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^user-config', views.UserConfigView.as_view()),
    url(r'^credit-info', views.CreditInfoView.as_view()),
    url(r'^bank/', views.get_bank),
    url(r'^bank-account-category/', views.get_bank_account_category),
    url(r'^change-email', views.DeprecatedChangeCurrentEmail.as_view()),
    url(
        r'^master-agreement-template/(?P<application_id>[0-9]+)$',
        views.MasterAgreementTemplate.as_view(),
    ),
    url(
        r'^submit-master-agreement/(?P<application_id>[0-9]+)$',
        views.GenerateMasterAgreementView.as_view(),
    ),
    url(r'^limit-timer', views.LimitTimerView.as_view()),
    url(r'^list-bank-name/', views.ListBankNameView.as_view()),
    url(r'^action$', views.CustomerActionView.as_view()),
    url(r'^appsflyer$', views.CustomerAppsflyerView.as_view()),
    url(r'^delete-allowed', views.IsCustomerDeleteAllowedView.as_view()),
    url(r'^delete-request', views.RequestCustomerDeletionView.as_view()),
    url(r'^customer-data/$', views.CustomerDataView.as_view()),
    url(r'^upload-document/$', views.CustomerDataUploadView.as_view()),
    url(r'^customer-data/submit-payday-change/$', views.CustomerDataPaydayChangeView.as_view()),
    url(r'^submit-product-locked', views.SubmitProductLocked.as_view()),
    url(r'experiment$', views.FeatureExperimentStoredView.as_view()),
    url(r'geolocation$', views.CustomerGeolocationView.as_view()),
    url(r'latest-transactions/$', views.CustomerLatestTransactionsView.as_view()),
    url(r'point-histories/$', views.CustomerLoyaltyPointHistoryAPIView.as_view()),
    url(r'consent-withdrawal/check-allowed/$', views.IsConsentWithdrawalAllowedView.as_view()),
    url(r'consent-withdrawal/request/$', views.SubmitConsentWithdrawalView.as_view()),
    url(
        r'consent-withdrawal/change-status/(?P<action>[a-zA-Z_]+)$',
        views.ChangeStatusConsentWithdrawalView.as_view(),
    ),
    url(r'feature-restrictions/', views.CustomerRestrictionsView.as_view()),
    url(r'consent-withdrawal/get-status/', views.CustomerGetStatusView.as_view()),
    url(
        r'consent-withdrawal/send-email/(?P<action>[a-zA-Z_]+)$',
        views.SendEmaiConsentWithdrawal.as_view(),
    ),
] + crm_v1.urlpatterns
