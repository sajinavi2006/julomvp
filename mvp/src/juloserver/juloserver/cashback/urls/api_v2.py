from ..views import api_views as views

from django.conf.urls import url
from rest_framework import routers

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^options_info$', views.CashbackOptionsInfoV2.as_view()),
]
