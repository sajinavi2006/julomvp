from __future__ import unicode_literals

from django.conf.urls import include, url
from rest_framework import routers

from juloserver.merchant_financing.lender_dashboard import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r"^", include(router.urls)),
    url(
        r"^loan/approval",
        views.LenderApprovalView.as_view(),
    ),
    url(
        r"^loan/need-approval",
        views.ListApplicationViews.as_view(),
    ),
    url(
        r"^loan",
        views.ListApplicationPastViews.as_view(),
    ),
]
