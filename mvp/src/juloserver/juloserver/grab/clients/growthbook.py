from django.conf import settings
from growthbook import GrowthBook


class GrabGrowthbookClient(object):
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GrabGrowthbookClient, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.api_host = settings.GROWTHBOOK_API_HOST
        self.client_key = settings.GROWTHBOOK_CLIENT_KEY

    def load_growthbook_features(self, callback_function):
        growthbook = GrowthBook(
            api_host=self.api_host,
            client_key=self.client_key,
            on_experiment_viewed=callback_function
        )
        growthbook.load_features()
        return growthbook
