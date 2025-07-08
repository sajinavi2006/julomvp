from django.conf.urls import include, url

urlpatterns = [
    url(r'^bca/v1/', include('juloserver.autodebet.urls.urls_bca_api_v1', namespace='v1')),
    url(r'^v1/', include('juloserver.autodebet.urls.api_v1', namespace='v1')),
    url(r'^bri/v1/', include('juloserver.autodebet.urls.urls_bri_api_v1', namespace='bri_v1')),
    url(r'^gopay/v1/', include('juloserver.autodebet.urls.urls_gopay_api_v1',
                               namespace='gopay_v1')),
    url(r'^v2/', include('juloserver.autodebet.urls.api_v2', namespace='v2')),
    url(r'^v3/', include('juloserver.autodebet.urls.api_v3', namespace='v3')),
    url(
        r'^mandiri/v1/',
        include('juloserver.autodebet.urls.urls_mandiri_api_v1', namespace='mandiri_v1'),
    ),
    url(r'^bni/v1/', include('juloserver.autodebet.urls.urls_bni_api_v1', namespace='bni_v1')),
    url(r'^dana/v1/', include('juloserver.autodebet.urls.urls_dana_api_v1', namespace='dana_v1')),
    url(r'^ovo/v1/', include('juloserver.autodebet.urls.urls_ovo_api_v1', namespace='ovo_v1')),
]
