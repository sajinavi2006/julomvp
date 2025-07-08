from django.conf.urls import url
from rest_framework import routers
from juloserver.dana.onboarding import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'registration-account-creation', views.DanaAccountBindView.as_view(), name="account_bind"),
    url(r'user/update/account-info', views.DanaAccountUpdateView.as_view(), name="account_update"),
    url(
        r'registration-account-inquiry',
        views.DanaAccountInquiryView.as_view(),
        name="account_inquiry",
    ),
    url(r'user/query/account-info', views.DanaAccountInfoView.as_view(), name="query_account_info"),
    # url(
    #     r'user/query/temp-account-info',
    #     views.DanaAccountInfoTempView.as_view(),
    #     name="query_account_info_temp",
    # ),
]
