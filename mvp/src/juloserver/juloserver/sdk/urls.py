from django.conf.urls import include, url
from rest_framework import routers


from . import views
router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),

    url(r'dropdowndata/', views.DropDownApi.as_view()),

    url(r'^scrap/$', views.PartnerScrapedDataViewSet.as_view()),
    url(r'^scrapeddata/$', views.PartnerScrapedDataViewSet.as_view()),

    url(r'^authentication/$', views.PartnerRegisterUser.as_view()),

    # url(r'^loans/(?P<nik>[0-9]+)/$$', views.PartnerLoanListView.as_view()),
    # url(r'^loan/(?P<application_xid>[0-9]+)/$', views.PartnerLoanRetrieveUpdateView.as_view()),

    url(r'^applications/(?P<application_xid>[0-9]+)/$', views.PartnerApplicationView.as_view()),
    url(r'^applications/(?P<application_xid>[0-9]+)/validate/$', views.ValidateView.as_view()),
    url(r'^applications/(?P<application_xid>[0-9]+)/activation/$', views.ActivationView.as_view()),
    url(r'^applications/(?P<application_xid>[0-9]+)/accept_activation/$', views.AcceptActivationView.as_view()),
    url(r'^applications/(?P<application_xid>[0-9]+)/credit-score/$', views.CreditScoreView.as_view()),
    url(r'^applications/(?P<application_xid>[0-9]+)/images/$', views.ImageListCreateView.as_view()),
    url(r'^applications/(?P<application_xid>[0-9]+)/invoices/$', views.SendInvociesView.as_view()),
    url(r'^applications/(?P<application_xid>[0-9]+)/loan/$', views.PartnerLoanPaymentView.as_view()),
    url(r'^applications/(?P<application_xid>[0-9]+)/application_status/$', views.PartnerApplicationStatusView.as_view()),

    #api to upload sdk log csv
    url(r'^scraped-data-csv/upload', views.SDKLogApi.as_view()),


    # api pede get digisign url
    url(r'^digisign_pede_webview/(?P<application_xid>[0-9]+)/$',
        views.DigisignPedeWebView.as_view()),
]
