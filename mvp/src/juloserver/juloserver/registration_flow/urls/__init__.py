from django.conf.urls import include, url

urlpatterns = [
    url(r'^v1/', include('juloserver.registration_flow.urls.api_v1', namespace='v1')),
    url(r'^v2/', include('juloserver.registration_flow.urls.api_v2', namespace='v2')),
    url(r'^v3/', include('juloserver.registration_flow.urls.api_v3', namespace='v3')),
    url(r'^v4/', include('juloserver.registration_flow.urls.api_v4', namespace='v4')),
    url(r'^v5/', include('juloserver.registration_flow.urls.api_v5', namespace='v5')),
    url(r'^v6/', include('juloserver.registration_flow.urls.api_v6', namespace='v6')),
]
