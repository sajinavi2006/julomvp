import geohash

from juloserver.geohash.constants import SUPPORTED_GEOHASH_PRECISIONS
from juloserver.geohash.models import (
    AddressGeolocationGeohash,
    GeohashReverse,
)
from juloserver.geohash.tasks import store_reverse_geohash


def save_address_geolocation_geohash(address_geolocation):
    """
    Save the geohash data based on AddressGeolocation data
    Args:
        address_geolocation (AddressGeolocation):

    Returns:
        AddressGeolocationGeohash
    """
    latitude = float(address_geolocation.latitude)
    longitude = float(address_geolocation.longitude)

    if (
        AddressGeolocationGeohash.objects
            .filter(address_geolocation=address_geolocation)
            .exists()
    ):
        return

    geohash_data = _generate_geohash_data(latitude, longitude, is_generate_reverse_data=True)
    return AddressGeolocationGeohash.objects.create(
        address_geolocation=address_geolocation,
        **geohash_data,
    )


def geohash_precision(geohash_str):
    """
    Get the precision of the geohash based on the geohash string

    Args:
        geohash_str (string): Geohash string

    Returns:
        integer
    """
    return len(geohash_str)


def _generate_geohash_data(latitude, longitude, is_generate_reverse_data=False):
    """
    Generate the dictionary with the keys: geohash6, geohash7. geohash8, geohash9.
    The list of geohash is based on SUPPORTED_GEOHASH_PRECISIONS
    Args:
        latitude (float): latitude
        longitude (float): Longitude
        is_generate_reverse_data (bool): Flag to store
            the reverse geohash data to `ops.geohash_reverse`

    Returns:
        dict: Example
            {
                "geohash6": '123456',
                "geohash7": '1234567',
                "geohash8": '12345678',
                "geohash9": '123456789',
            }

    """
    data = {}
    for precision in SUPPORTED_GEOHASH_PRECISIONS:
        geohash_str = geohash.encode(latitude, longitude, precision)
        data['geohash{}'.format(precision)] = geohash_str

        # Store the reverse data to `ops.geohash_reverse`
        if is_generate_reverse_data:
            store_reverse_geohash.delay(geohash_str)

    return data


def get_geohash_reverse(geohash_str, is_create=False):
    """
    Get the geohash reverse object based on geohash string.
    Args:
        geohash_str (str): Geohash string
        is_create (bool): create the geohash if not exists
    Returns:
        GeohashReverse
    """
    geohash_reverse = GeohashReverse.objects.filter(geohash=geohash_str).last()
    if not geohash_reverse and is_create:
        geohash_reverse = store_reverse_geohash(geohash_str)

    return geohash_reverse
