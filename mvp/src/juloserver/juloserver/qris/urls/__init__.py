from django.conf.urls import include, url


urlpatterns = [
    url(r'^v1/', include('juloserver.qris.urls.api_v1', namespace='api')),
    url(r'^v2/', include('juloserver.qris.urls.api_v2', namespace='api')),
]
