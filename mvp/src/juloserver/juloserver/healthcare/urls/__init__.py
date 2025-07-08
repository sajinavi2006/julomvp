from django.conf.urls import include, url


urlpatterns = [
    url(r'^v1/', include('juloserver.healthcare.urls.api_v1')),
]
