from django.conf.urls import url
from rest_framework import routers
from ..views import MagicLinkView

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^verify/(?P<token>.*)', MagicLinkView.as_view()),
]
