from django.conf.urls import url
from rest_framework import routers
from juloserver.ecommerce.views import views_api_v2

router = routers.DefaultRouter()
regex_uuid4 = '[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'

urlpatterns = [
    url(r'^category', views_api_v2.EcommerceCategoryView.as_view()),
    url(
        r'^get-iprice-transaction-info/(?P<transaction_xid>{})$'.format(regex_uuid4),
        views_api_v2.IpriceGetTransactionData.as_view(),
    ),
]
