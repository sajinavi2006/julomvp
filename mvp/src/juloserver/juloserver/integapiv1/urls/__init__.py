from django.conf.urls import include, url

urlpatterns = [
    url(r'^api/integration/v1/', include('juloserver.integapiv1.urls.api_v1', namespace='v1')),
    url(
        r'^bca/openapi/v1.0/', include('juloserver.integapiv1.urls.bca_snap', namespace='bca_snap')
    ),
    url(
        r'^faspay-snap/v1.0/',
        include('juloserver.integapiv1.urls.faspay_snap', namespace='faspay_snap'),
    ),
    url(
        r'^api/comm-proxy/v1/',
        include('juloserver.integapiv1.urls.comm_proxy', namespace='comm_proxy'),
    ),
]
