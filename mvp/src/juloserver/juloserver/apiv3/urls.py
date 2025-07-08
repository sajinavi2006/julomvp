from django.conf.urls import include, url
from rest_framework import routers

from . import views

router = routers.DefaultRouter()


urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^address/provinces$', views.AddressLookupView.as_view({"get": "get_provinces"})),
    url(r'^address/cities$', views.AddressLookupView.as_view({"post": "get_cities"})),
    url(r'^address/districts$', views.AddressLookupView.as_view({"post": "get_districts"})),
    url(r'^address/subdistricts$', views.AddressLookupView.as_view({"post": "get_subdistricts"})),
    url(r'^address/info$', views.AddressLookupView.as_view({"post": "get_info"})),
    url(r'^additional/info/$', views.AdditionalInfoView.as_view()),
    # appsflyer api
    url(r'^appsflyer$', views.AppsflyerView.as_view()),
    # api to add geolocation
    url(r'^devicegeolocations$', views.DeviceGeolocationView.as_view()),
    # api to get server time
    url(r'^servertime$', views.ServerTimeView.as_view()),
    # api to get term and privacy in html code
    url(r'^termsprivacy$', views.get_terms_privacy),
    # api to get bank data
    url(
        r'^product-line/(?P<product_line_code>[0-9]+)/dropdown_bank_data/', views.BankApi.as_view()
    ),
    # boost urls
    url(r'^booster/', include('juloserver.boost.urls')),
    url(r'^application/(?P<pk>[0-9]+)/$', views.ApplicationUpdateV3.as_view()),
    # api for health check
    url(r'^healthcheck$', views.HealthCheckView.as_view()),
    # Endpoint for uploading DSD to anaserver and starting ETL
    url(r'^etl/dsd/$', views.DeviceScrapedDataUploadV3.as_view()),
    # faq section
    url(r'^faq$', views.FAQFeatureView.as_view()),
    url(r'^etl-clcs/dsd/$', views.DeviceScrapedDataUploadCLCSV3.as_view()),
]
