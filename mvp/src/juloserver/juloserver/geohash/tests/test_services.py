from django.test import TestCase

from juloserver.geohash.models import GeohashReverse
from juloserver.geohash.services import (
    get_geohash_reverse,
    save_address_geolocation_geohash,
)
from juloserver.geohash.tests.factories import (
    AddressGeolocationGeohashFactory,
    GeohashReverseFactory,
)
from juloserver.julo.tests.factories import AddressGeolocationFactory


class TestSaveAddressGeolocationGeohash(TestCase):
    def setUp(self):
        self.address_geolocation = AddressGeolocationFactory(
            latitude=-88.22972059,
            longitude=-122.19605684
        )

    def test_save_geohash_data(self):
        ret_val = save_address_geolocation_geohash(self.address_geolocation)

        self.assertEqual('123456', ret_val.geohash6)
        self.assertEqual('1234567', ret_val.geohash7)
        self.assertEqual('12345678', ret_val.geohash8)
        self.assertEqual('123456789', ret_val.geohash9)

    def test_skip_if_exists(self):
        AddressGeolocationGeohashFactory(address_geolocation=self.address_geolocation)
        ret_val = save_address_geolocation_geohash(self.address_geolocation)

        self.assertIsNone(ret_val)


class TestGetGeohashReverse(TestCase):
    def test_is_create_true(self):
        geohash_reverse = get_geohash_reverse('12345678', is_create=True)
        self.assertTrue(GeohashReverse.objects.filter(geohash='12345678').exists())
        self.assertEqual('12345678', geohash_reverse.geohash)

    def test_exist_and_is_create_true(self):
        GeohashReverseFactory(geohash='12345678')
        geohash_reverse = get_geohash_reverse('12345678', is_create=True)
        self.assertEqual(1, GeohashReverse.objects.count())
        self.assertEqual('12345678', geohash_reverse.geohash)

    def test_is_create_false(self):
        geohash_reverse = get_geohash_reverse('12345678', is_create=False)
        self.assertFalse(GeohashReverse.objects.filter(geohash='12345678').exists())
        self.assertIsNone(geohash_reverse)

    def test_exist_and_is_create_false(self):
        GeohashReverseFactory(geohash='12345678')
        geohash_reverse = get_geohash_reverse('12345678', is_create=False)
        self.assertEqual(1, GeohashReverse.objects.count())
        self.assertEqual('12345678', geohash_reverse.geohash)
