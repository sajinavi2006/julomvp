from django.conf.urls import url
from rest_framework import routers

from juloserver.registration_flow import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^register$', views.RegisterUserV4.as_view()),
]
