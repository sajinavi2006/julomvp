from django.conf.urls import include, url

urlpatterns = [
    url(r'^v1/channeling/', include('juloserver.followthemoney.urls.channeling_urls')),
    url(r'^v1.1/', include('juloserver.followthemoney.urls.application_urls')),
    url(r'^v1/', include('juloserver.followthemoney.urls.j1_urls')),
    url(r'^v1/', include('juloserver.followthemoney.urls.v1_urls')),
]
