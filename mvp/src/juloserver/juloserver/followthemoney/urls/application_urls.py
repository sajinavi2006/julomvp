from __future__ import unicode_literals
from __future__ import absolute_import

from django.conf.urls import include, url

from rest_framework import routers

from juloserver.followthemoney.views import application_views
from juloserver.followthemoney.withdraw_view import views as withdraw_view

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^list_application/', application_views.ListApplicationViews.as_view(), name='list_application'),
    url(r'^list_application_past/', application_views.ListApplicationPastViews.as_view(), name='list_application_past'),
    url(r'^loan_detail/', application_views.ListLoanDetail.as_view()),
    url(r'^create_bucket/', application_views.CreateLenderBucketViews.as_view(), name='create_lender_bucket'),

]
