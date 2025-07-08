from django.conf.urls import include, url


urlpatterns = [
    url(r'^v1/', include('juloserver.julo_financing.urls.api_v1', namespace='api')),
]
