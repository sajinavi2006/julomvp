import geohash
from celery import task

from juloserver.geohash.models import GeohashReverse


@task(queue='low')
def store_reverse_geohash(geohash_string):
    """
    Save the GeohashReverse data
    Args:
        geohash_string (str): The geohash string

    Returns:
        GeohashReverse
    """
    latitude, longitude = geohash.decode(geohash_string)
    bbox_value = geohash.bbox(geohash_string)
    precision = len(geohash_string)
    geohash_reverse, _ = GeohashReverse.objects.get_or_create(
        geohash=geohash_string,
        defaults={
            'latitude': latitude,
            'longitude': longitude,
            'min_lat': bbox_value['s'],
            'min_long': bbox_value['w'],
            'max_lat': bbox_value['n'],
            'max_lon': bbox_value['e'],
            'precision': precision,
        }
    )
    return geohash_reverse
