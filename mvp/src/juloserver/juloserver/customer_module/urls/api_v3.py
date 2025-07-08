from django.conf.urls import url
from rest_framework import routers

from juloserver.customer_module.views import views_api_v3

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^credit-info', views_api_v3.CreditInfoView.as_view()),
    url(r'^bank-account-destination', views_api_v3.BankAccountDestinationViewV2.as_view()),
    url(r'^change-phone', views_api_v3.ChangeCustomerPrimaryPhoneNumber.as_view()),
    url(r'^change-email', views_api_v3.ChangeCurrentEmailV3.as_view()),
    url(
        r'^master-agreement-template/(?P<application_id>[0-9]+)$',
        views_api_v3.MasterAgreementTemplate.as_view()),
    url(r'^limit-timer', views_api_v3.LimitTimerView.as_view()),
]
