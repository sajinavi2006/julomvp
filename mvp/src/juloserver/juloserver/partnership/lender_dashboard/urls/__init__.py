from django.conf.urls import include, url

from . import v1, v2

urlpatterns = [url(r"", include(v1)), url(r"^v2/", include(v2))]
