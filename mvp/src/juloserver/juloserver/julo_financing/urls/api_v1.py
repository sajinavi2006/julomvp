from __future__ import unicode_literals
from rest_framework import routers
from django.conf.urls import url
from juloserver.julo_financing.views.view_api_v1 import (
    EntryPointWebView,
    JFinancingProductListView,
    JFinancingProductDetailView,
    JFinancingLoanCalculationView,
    JFinancingSubmitView,
    TransactionHistoryListView,
    JFinancingUploadSignatureView,
    JFinancingTransactionDetailView,
    JFinancingLoanAgreementContentView,
)

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^entry-point', EntryPointWebView.as_view()),
    url(
        r'^products/(?P<product_id>[0-9]+)/(?P<financing_token>.+)$',
        JFinancingProductDetailView.as_view(),
    ),
    url(r'^products/(?P<financing_token>.+)$', JFinancingProductListView.as_view()),
    url(r'^loan-duration/(?P<financing_token>.+)/$', JFinancingLoanCalculationView.as_view()),
    url(r'^customer/checkouts/(?P<financing_token>.+)$', TransactionHistoryListView.as_view()),
    url(r'^submit/(?P<financing_token>.+)$', JFinancingSubmitView.as_view()),
    url(
        r'^signature/upload/(?P<checkout_id>[0-9]+)/(?P<financing_token>.+)$',
        JFinancingUploadSignatureView.as_view(),
    ),
    url(
        r'^customer/checkout/(?P<checkout_id>[0-9]+)/(?P<financing_token>.+)$',
        JFinancingTransactionDetailView.as_view(),
    ),
    url(
        (r'^agreement/content/(?P<checkout_id>[0-9]+)/(?P<financing_token>.+)$'),
        JFinancingLoanAgreementContentView.as_view(),
    ),
]
