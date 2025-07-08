from django.conf.urls import include, url

from . import urls_v1, urls_v2

urlpatterns = [url(r"^v1/", include(urls_v1)), url(r"^v2/", include(urls_v2))]
