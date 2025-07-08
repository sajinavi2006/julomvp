from __future__ import unicode_literals
from __future__ import absolute_import

from django.conf.urls import include, url

from rest_framework import routers

from juloserver.balance_consolidation.views import views_api_v1

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^get-fintechs/?$', views_api_v1.GetFintechs.as_view()),
    url(
        r'^submit/(?P<token>.{204})/$',
        views_api_v1.BalanceConsolidationSubmitView.as_view(),
        name='submit',
    ),
    url(
        r'^signature/upload/(?P<balance_consolidation_id>[0-9]+)/(?P<token>.{204})/',
        views_api_v1.BalanceConsolidationUploadSignatureView.as_view(),
        name='balance_consolidation_upload_signature',
    ),
    url(
        r'^get_loan_duration/(?P<token>.{204})$',
        views_api_v1.BalanceConsolidationGetLoanDurationView.as_view(),
        name='loan_duration',
    ),
    url(r'^info-card/?$', views_api_v1.BalanceConsolidationInfoAPIView.as_view(), name='info_card'),
    url(
        r'^agreement/content/(?P<balance_consolidation_id>[0-9]+)/(?P<token>.{204})/',
        views_api_v1.TemporaryLoanAgreementContentWebView.as_view(),
    ),
    url(r'^customer-info/(?P<token>.{204})/', views_api_v1.CustomerInfoView.as_view()),
]
