from django.conf.urls import include, url


urlpatterns = [
    url(r'^v1/', include('juloserver.loyalty.urls.api_v1')),
    url(r'^v2/', include('juloserver.loyalty.urls.api_v2')),
]
