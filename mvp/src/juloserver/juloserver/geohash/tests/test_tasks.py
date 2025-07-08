from django.test import TestCase

from juloserver.geohash.tasks import store_reverse_geohash


class TestStoreReverseGeohash(TestCase):
    def test_store_geohash(self):
        ret_val = store_reverse_geohash('1234567')
        self.assertEqual(7, ret_val.precision)
        self.assertEqual(-88.22914123535156, ret_val.latitude)
        self.assertEqual(-122.19612121582031, ret_val.longitude)
        self.assertEqual(-88.22982788085938, ret_val.min_lat)
        self.assertEqual(-122.19680786132812, ret_val.min_long)
        self.assertEqual(-88.22845458984375, ret_val.max_lat)
        self.assertEqual(-122.1954345703125, ret_val.max_lon)
