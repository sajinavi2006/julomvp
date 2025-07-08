from django.conf.urls import include, url

urlpatterns = [
    url(r'^v1/', include('juloserver.payment_point.urls.api_v1')),
    url(r'^v2/', include('juloserver.payment_point.urls.api_v2')),
    url(r'^v3/', include('juloserver.payment_point.urls.api_v3')),
]
