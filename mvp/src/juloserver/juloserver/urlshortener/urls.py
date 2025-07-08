from __future__ import unicode_literals

from django.conf.urls import url

from .views import UrlShortenerView

urlpatterns = [
    url(r'^(?P<shorturl>[A-Za-z0-9]+)?$', UrlShortenerView.as_view()),
]
