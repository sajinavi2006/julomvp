from django.conf.urls import url
from rest_framework import routers

from juloserver.customer_module.views import views_api_v2

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^credit-info', views_api_v2.CreditInfoView.as_view()),
    url(
        r'^bank-account-destination/(?P<customer_id>[0-9]+)$',
        views_api_v2.BankAccountDestinationView.as_view(),
    ),
    url(r'^bank/', views_api_v2.BankView.as_view()),
    url(r'update-analytics-data', views_api_v2.GoogleAnalyticsInstanceDataView.as_view()),
    url(r'^change-email', views_api_v2.ChangeCurrentEmailV2.as_view()),
    url(
        r'^master-agreement-template/(?P<application_id>[0-9]+)$',
        views_api_v2.MasterAgreementTemplate.as_view()),
    url(
        r'^submit-master-agreement/(?P<application_id>[0-9]+)$',
        views_api_v2.GenerateMasterAgreementView.as_view()),
    url(r'^limit-timer', views_api_v2.LimitTimerView.as_view()),
]
