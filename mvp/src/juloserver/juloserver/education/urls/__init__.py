from django.conf.urls import include, url


urlpatterns = [
    url(r'^v1/', include('juloserver.education.urls.api_v1')),
]
