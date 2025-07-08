from django.conf.urls import include, url

urlpatterns = [
    url(r'^v1/', include('juloserver.dana_linking.urls.api_v1', namespace='v1')),
    url(
        r'^webhook/v1/', include('juloserver.dana_linking.urls.webhook_v1', namespace='webhook_v1')
    ),
]
