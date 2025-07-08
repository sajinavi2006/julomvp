from __future__ import unicode_literals

from django.conf.urls import url

from rest_framework import routers

from juloserver.healthcare.views import views_api_v1

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^users', views_api_v1.HeathCareUserAPIListCreateView.as_view()),
    url(r'^faq/?$', views_api_v1.HealthcareFAQView.as_view()),
    url(r'^platforms', views_api_v1.HelathcarePlatformAPIListView.as_view()),
    url(r'^user/(?P<pk>[0-9]+)$', views_api_v1.HealthcareUserAPICreatePutDeleteView.as_view()),
    url(r'^user', views_api_v1.HealthcareUserAPICreatePutDeleteView.as_view()),
]
