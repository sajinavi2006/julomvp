from django.conf.urls import url
from rest_framework import routers
from juloserver.ecommerce.views import views_api_v1

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^category', views_api_v1.EcommerceCategoryView.as_view()),
    url(r'^callbacks/iprice-checkout', views_api_v1.IpriceCheckoutCallbackView.as_view()),
    url(r'^callback/juloshop/checkout$', views_api_v1.JuloShopCheckoutCallbackView.as_view()),
    url(r'juloshop/get_details', views_api_v1.JuloShopTransactionDetails.as_view())
]
