from django.db import models
from juloserver.julocore.data.models import TimeStampedModel
from juloserver.julocore.customized_psycopg2.models import BigAutoField

class GeohashReverse(TimeStampedModel):
    # Radius in KM, The value is hardcoded based on the business requirements.
    PRECISION_TO_RADIUS_MAP = {
        6: 2.44,
        7: 0.30,
        8: 0.08,
        9: 0.01,
    }
    geohash = models.TextField(db_column='geohash', primary_key=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    min_lat = models.FloatField(blank=True, null=True)
    min_long = models.FloatField(blank=True, null=True)
    max_lat = models.FloatField(blank=True, null=True)
    max_lon = models.FloatField(blank=True, null=True)
    precision = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'geohash_reverse'

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.geohash)

    @property
    def estimated_radius(self):
        return self.PRECISION_TO_RADIUS_MAP[self.precision]

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.geohash)


class AddressGeolocationGeohash(TimeStampedModel):
    id = BigAutoField(db_column='address_geolocation_geohash_id', primary_key=True)
    address_geolocation = models.ForeignKey(
        'julo.AddressGeolocation',
        models.DO_NOTHING,
        db_column='address_geolocation_id')
    geohash6 = models.TextField()
    geohash7 = models.TextField()
    geohash8 = models.TextField()
    geohash9 = models.TextField()

    class Meta:
        db_table = 'address_geolocation_geohash'
        index_together = [
            ['geohash8'],
            ['geohash9']
        ]
