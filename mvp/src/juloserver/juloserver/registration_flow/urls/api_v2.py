from django.conf.urls import include, url
from rest_framework import routers

from juloserver.registration_flow import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    # Check phone number existance
    url(r'^check', views.CheckPhoneNumber.as_view()),
    url(r'^register', views.RegisterPhoneNumberV2.as_view()),
    url(r'^validate', views.ValidateNikEmailV2.as_view()),
]
