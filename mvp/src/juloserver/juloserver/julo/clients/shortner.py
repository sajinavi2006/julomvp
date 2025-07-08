from builtins import object
import bitly_api
from django.conf import settings
class UrlShortenServices(object):
    def __init__(self):
        self.access_token = settings.BITLY_TOKEN
        self.shorten = bitly_api.Connection(access_token=self.access_token)

    def short(self, url):
        return self.shorten.shorten(url)
