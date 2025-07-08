from django.conf.urls import include, url
from rest_framework import routers

from juloserver.registration_flow import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^register', views.RegisterUserV5.as_view()),
]
