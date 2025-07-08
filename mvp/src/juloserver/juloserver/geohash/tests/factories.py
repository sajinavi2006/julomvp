from factory import (
    DjangoModelFactory,
    SubFactory,
)

from juloserver.geohash.models import (
    AddressGeolocationGeohash,
    GeohashReverse,
)
from juloserver.julo.tests.factories import AddressGeolocationFactory


class AddressGeolocationGeohashFactory(DjangoModelFactory):
    class Meta(object):
        model = AddressGeolocationGeohash

    address_geolocation = SubFactory(AddressGeolocationFactory)
    geohash6 = 'qwerty'
    geohash7 = 'qwertyu'
    geohash8 = 'qwertyui'
    geohash9 = 'qwertyuio'


class GeohashReverseFactory(DjangoModelFactory):
    class Meta:
        model = GeohashReverse
        django_get_or_create = ('geohash', )

    geohash = 'qwertyu'
