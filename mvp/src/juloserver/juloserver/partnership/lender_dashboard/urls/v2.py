from django.conf.urls import url
from rest_framework import routers

from juloserver.partnership.lender_dashboard.views import v2 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^list_application/', views.PartnershipListApplicationViews.as_view()),
    url(r'^list_application_past/', views.PartnershipListApplicationPastViews.as_view()),
    url(r'^loan_detail/', views.PartnershipListLoanDetailViewsV2.as_view()),
    url(r'^create_bucket/', views.PartnershipCreateLenderBucketViews.as_view()),
]
