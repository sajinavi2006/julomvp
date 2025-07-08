from __future__ import absolute_import
from django.conf.urls import url

from spyne.protocol.soap import Soap11
from spyne.server.django import DjangoView

from .views import julosoap, application, PartnerLoanService


urlpatterns = [
    url(r'^julosoap/', julosoap),
    url(r'^partner_loan/', DjangoView.as_view(
        services=[PartnerLoanService], tns='julosoap.service.partnerloan',
        in_protocol=Soap11(validator='lxml'), out_protocol=Soap11())),
    url(r'^api/', DjangoView.as_view(application=application)),
]