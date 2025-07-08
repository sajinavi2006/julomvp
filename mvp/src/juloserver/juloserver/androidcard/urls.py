from __future__ import unicode_literals

from django.conf.urls import include, url

from rest_framework import routers

from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^other_loan/', views.other_loan_view, name="other_loan"),
]
