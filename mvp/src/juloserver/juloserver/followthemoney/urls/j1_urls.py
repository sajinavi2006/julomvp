from __future__ import unicode_literals
from __future__ import absolute_import

from django.conf.urls import include, url

from rest_framework import routers

from juloserver.followthemoney.views import j1_views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^list_application/', j1_views.ListApplicationViews.as_view()),
    url(r'^list_application_past/', j1_views.ListApplicationPastViews.as_view()),
    url(r'^loan_detail/', j1_views.ListLoanDetail.as_view()),
    url(r'^create_bucket/', j1_views.CreateLenderBucketViews.as_view()),
]
