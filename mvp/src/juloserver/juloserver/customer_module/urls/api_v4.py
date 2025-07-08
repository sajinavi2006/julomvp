from django.conf.urls import url
from rest_framework import routers

from juloserver.customer_module.views import views_api_v4

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^bank-account-destination', views_api_v4.BankAccountDestinationViewV4.as_view()),
    url(r'^device$', views_api_v4.CustomerDeviceView.as_view()),
    url(
        r'^request-change-phone/submit/(?P<reset_key>[A-Za-z0-9]+)/',
        views_api_v4.SubmitRequestChangePhoneViewSet.as_view(),
        name="submit-request-phone",
    ),
    url(
        r'^request-change-phone/(?P<reset_key>[A-Za-z0-9]+)/$',
        views_api_v4.GetFormChangePhoneViewSet.as_view(),
        name="form-request-phone",
    ),
    url(r'^request-change-phone$', views_api_v4.RequestChangePhoneViewSet.as_view()),
    url(r'^verify-bank-account', views_api_v4.VerifyBankAccountDestinationV4.as_view()),
]
