from django.conf.urls import url
from rest_framework import routers
from juloserver.partnership.lender_dashboard.views import v1 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(
        r'^loans/pending-approval/',
        views.PartnershipListPendingLoanViews.as_view(),
        name="partnership_list_loan_views",
    ),
    url(
        r'^loans/approved/',
        views.PartnershipListApprovedLoanViews.as_view(),
        name="partnership_list_past_loan_views",
    ),
    url(
        r'^loans/detail/',
        views.PartnershipListLoanDetailViews.as_view(),
        name="partnership_list_loan_detail_views",
    ),
]
