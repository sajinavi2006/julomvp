from __future__ import unicode_literals

from django.conf.urls import url

from rest_framework import routers

from juloserver.loan.views import views_api_v5 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^loan-duration', views.LoanCalculation.as_view()),
]
