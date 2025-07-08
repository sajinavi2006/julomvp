from django.conf.urls import include, url

urlpatterns = [
    url(r'^v1/', include('juloserver.credit_card.urls.api_v1', namespace='v1')),
]
