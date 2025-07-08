from django.conf.urls import include, url

urlpatterns = [
    url(r'^v1/', include('juloserver.application_form.urls.url_v1', namespace='v1')),
    url(r'^v2/', include('juloserver.application_form.urls.url_v2', namespace='v2')),
]
