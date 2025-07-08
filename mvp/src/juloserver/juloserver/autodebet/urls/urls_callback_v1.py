from django.conf.urls import url
from rest_framework import routers

from juloserver.autodebet.views import views_callback as views
router = routers.DefaultRouter()

urlpatterns = [
    url(r'^notification$', views.BCAAccountNotificationView.as_view()),
    url(r'^access-token$', views.BCAAccessTokenView.as_view()),
]
