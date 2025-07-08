from django.conf.urls import url
from rest_framework import routers

from juloserver.autodebet.views import views_dana_api_v1 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^activation$', views.ActivationView.as_view()),
    url(r'^deactivation$', views.DeactivationView.as_view()),
    url(r'^reactivate$', views.ReactivationView.as_view()),
]
