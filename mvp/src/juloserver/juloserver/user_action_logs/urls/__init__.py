from django.conf.urls import include, url

urlpatterns = [
    url(r'^v1/', include('juloserver.user_action_logs.urls.api_v1', namespace='api_v1')),
]
