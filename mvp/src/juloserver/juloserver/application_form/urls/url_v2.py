from django.conf.urls import url
from rest_framework import routers

from juloserver.application_form.views import view_v2 as views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^application/(?P<pk>[0-9]+)$', views.ApplicationUpdate.as_view()),
    url(r'^reapply', views.ApplicationReapply.as_view()),
]
