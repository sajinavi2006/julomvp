from django.conf.urls import url
from rest_framework import routers
from juloserver.dana.collection import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'collection', views.DanaCollectionView.as_view(), name="collection_view"),
    url(r'^airudder/webhooks', views.AiRudderWebhooks.as_view()),
]
