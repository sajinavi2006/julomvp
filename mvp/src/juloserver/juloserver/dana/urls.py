from django.conf.urls import url, include
from rest_framework import routers

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include('juloserver.dana.onboarding.urls.api_v1', namespace='onboarding')),
    url(r'^', include('juloserver.dana.loan.urls.api_v1', namespace='loan')),
    url(r'^', include('juloserver.dana.repayment.urls.api_v1', namespace='repayment')),
    url(r'^', include('juloserver.dana.collection.urls.api_v1', namespace='collection')),
    url(r'^', include('juloserver.dana.refund.urls.api_v1', namespace='refund')),
]
