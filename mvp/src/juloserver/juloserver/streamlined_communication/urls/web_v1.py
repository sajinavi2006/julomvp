from django.conf.urls import url
from rest_framework import routers
from .. import web_views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^info_cards', web_views.WebInfoCards.as_view(),
        name='web_info_cards'),
]
