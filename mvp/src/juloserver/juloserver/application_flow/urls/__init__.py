from django.conf.urls import include, url

from . import api_v1, api_v2, web_v1

urlpatterns = [
    url(r"^v1/", include(api_v1)),
    url(r"^v2/", include(api_v2)),
    url(r"^web/v1/", include(web_v1)),
]
