from django.conf.urls import include, url


urlpatterns = [
    url(r'^v1/', include('juloserver.channeling_loan.urls.api_v1', namespace='api')),
]
