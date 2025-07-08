from django.conf.urls import include, url
from rest_framework import routers

from juloserver.fraud_portal.views.compare_page import (
    ApplicationScores,
    FaceMatching,
    FaceSimilarity,
    ApplicationInfo,
    BPJSAndDukcapilInfo,
    LoanInfo,
    ConnectionAndDevice,
    ApplicationsByDevice,
)
from juloserver.fraud_portal.views.homepage_view import (
    ApplicationList,
    StatusCodeList,
    ProductLineList,
    SuspiciousCustomerList,
    SuspiciousAppsList,
    BlacklistedGeohash5List,
    BlacklistedPostalCodeList,
    BlacklistedCustomerList,
    BlacklistedEmailDomainList,
    BlacklistedCompanyList,
    SuspiciousAsnList,
)

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^application-info', ApplicationInfo.as_view(), name="application-info"),
    url(r'^applications-by-device', ApplicationsByDevice.as_view(), name="application-info"),
    url(r'^application-scores', ApplicationScores.as_view(), name="application-scores"),
    url(r'^face-matching', FaceMatching.as_view(), name="face-matching"),
    url(r'^face-similarity', FaceSimilarity.as_view(), name="face-similarity"),
    url(r'^bpjs-dukcapil-info', BPJSAndDukcapilInfo.as_view(), name="bpjs-dukcapil-info"),
    url(r'^loan-info', LoanInfo.as_view(), name="loan-info"),
    url(r'^connection-and-device', ConnectionAndDevice.as_view(), name="connection-and-device"),
    url(r'^status-codes', StatusCodeList.as_view(), name="status-codes"),
    url(r'^product-lines', ProductLineList.as_view(), name="product-lines"),
    url(r'^applications', ApplicationList.as_view(), name="applications"),
    url(r'^suspicious-customers/upload',
        SuspiciousCustomerList.as_view({"post": "upload"}),
        name="suspicious-customers"
        ),
    url(r'^suspicious-customers',
        SuspiciousCustomerList.as_view({"get": "get", "post": "post", "delete": "delete"}),
        name="suspicious-customers"
        ),
    url(r'^suspicious-apps/upload',
        SuspiciousAppsList.as_view({"post": "upload"}),
        name="suspicious-apps"
        ),
    url(r'^suspicious-apps/(?P<pk>[0-9]+)$',
        SuspiciousAppsList.as_view({"delete": "delete"}),
        name="suspicious-apps"
        ),
    url(r'^suspicious-apps',
        SuspiciousAppsList.as_view({"get": "get", "post": "post"}),
        name="suspicious-apps"
        ),
    url(r'^blacklisted-geohash5s/upload',
        BlacklistedGeohash5List.as_view({"post": "upload"}),
        name="blacklisted-geohash5s"
        ),
    url(r'^blacklisted-geohash5s/(?P<pk>[0-9]+)$',
        BlacklistedGeohash5List.as_view({"delete": "delete"}),
        name="blacklisted-geohash5s"),
    url(r'^blacklisted-geohash5s',
        BlacklistedGeohash5List.as_view({"get": "get", "post": "post"}),
        name="blacklisted-geohash5s"
        ),
    url(r'^blacklisted-postal-codes/upload',
        BlacklistedPostalCodeList.as_view({"post": "upload"}),
        name="blacklisted-postal-codes"
        ),
    url(r'^blacklisted-postal-codes/(?P<pk>[0-9]+)$',
        BlacklistedPostalCodeList.as_view({"delete": "delete"}),
        name="blacklisted-postal-codes"
        ),
    url(r'^blacklisted-postal-codes',
        BlacklistedPostalCodeList.as_view({"get": "get", "post": "post"}),
        name="blacklisted-postal-codes"
        ),
    url(r'^blacklisted-customers/upload',
        BlacklistedCustomerList.as_view({"post": "upload"}),
        name="blacklisted-customers"
        ),
    url(r'^blacklisted-customers/(?P<pk>[0-9]+)$',
        BlacklistedCustomerList.as_view({"delete": "delete"}),
        name="blacklisted-customers"
        ),
    url(r'^blacklisted-customers',
        BlacklistedCustomerList.as_view({"get": "get", "post": "post"}),
        name="blacklisted-customers"
        ),
    url(r'^blocked-email-domains/upload',
        BlacklistedEmailDomainList.as_view({"post": "upload"}),
        name="blocked-email-domains"
        ),
    url(r'^blocked-email-domains/(?P<pk>[0-9]+)$',
        BlacklistedEmailDomainList.as_view({"delete": "delete"}),
        name="blocked-email-domains"
        ),
    url(r'^blocked-email-domains',
        BlacklistedEmailDomainList.as_view({"get": "get", "post": "post"}),
        name="blocked-email-domains"
        ),
    url(r'^blacklisted-companies/upload',
        BlacklistedCompanyList.as_view({"post": "upload"}),
        name="blacklisted-companies"
        ),
    url(r'^blacklisted-companies/(?P<pk>[0-9]+)$',
        BlacklistedCompanyList.as_view({"delete": "delete"}),
        name="blacklisted-companies"
        ),
    url(r'^blacklisted-companies',
        BlacklistedCompanyList.as_view({"get": "get", "post": "post"}),
        name="blacklisted-companies"),
    url(r'^suspicious-asns/upload',
        SuspiciousAsnList.as_view({"post": "upload"}),
        name="suspicious-asns"
        ),
    url(r'^suspicious-asns',
        SuspiciousAsnList.as_view({"get": "get", "post": "post", "delete": "delete"}),
        name="suspicious-asns"
        ),
]
