from __future__ import unicode_literals

from builtins import object

from rest_framework import filters

from ..julo.models import (
    AddressGeolocation,
    Application,
    AppVersionHistory,
    Device,
    DeviceGeolocation,
    FacebookData,
    Image,
    Loan,
    Offer,
    Payment,
)

"""
Applying Django REST framework's generic filtering to some models.
"""


class ApplicationFilter(filters.FilterSet):
    class Meta(object):
        model = Application


class DeviceFilter(filters.FilterSet):
    class Meta(object):
        model = Device


class ImageFilter(filters.FilterSet):
    class Meta(object):
        model = Image


class FacebookDataFilter(filters.FilterSet):
    class Meta(object):
        model = FacebookData


class OfferFilter(filters.FilterSet):
    class Meta(object):
        model = Offer


class LoanFilter(filters.FilterSet):
    class Meta(object):
        model = Loan


class PaymentFilter(filters.FilterSet):
    class Meta(object):
        model = Payment


class AddressGeolocationFilter(filters.FilterSet):
    class Meta(object):
        model = AddressGeolocation


class AppVersionHistory(filters.FilterSet):
    class Meta(object):
        model = AppVersionHistory


class DeviceGeolocationFilter(filters.FilterSet):
    class Meta(object):
        model = DeviceGeolocation
