from django.conf.urls import include, url

from juloserver.payback import views

urlpatterns = [
    url(r'cashback-promo/(?P<approval_token>[a-z0-9]+)/decision$',
        views.cashback_promo_decision, name="cashback_promo_decision"),
    url(r'^v1/', include('juloserver.payback.urls.api_v1', namespace='v1')),
    url(r'^v2/', include('juloserver.payback.urls.api_v2', namespace='v2')),
    url(r'^dana-biller/', include('juloserver.payback.urls.dana_biller', namespace='dana_biller')),
    url(r'cimb/v1.0/', include('juloserver.payback.urls.cimb_snap', namespace='cimb')),
    url(r'doku/', include('juloserver.payback.urls.doku_snap', namespace='doku')),
]
