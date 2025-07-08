from django.conf.urls import include, url

urlpatterns = [
    url(r'^v1/', include('juloserver.loan.urls.api_v1')),
    url(r'^v2/', include('juloserver.loan.urls.api_v2')),
    url(r'^v3/', include('juloserver.loan.urls.api_v3')),
    url(r'^v4/', include('juloserver.loan.urls.api_v4')),
    url(r'^v5/', include('juloserver.loan.urls.api_v5')),
]
