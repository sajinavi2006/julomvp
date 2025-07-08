from django.conf import settings
from google.cloud import storage
from google.oauth2 import service_account


class GoogleCloudService(object):
    def __init__(self):
        self.credentials = service_account.Credentials.from_service_account_file(
            settings.KOLEKO_GOOGLE_CLOUD_STORAGE_CREDENTIAL)
        self.storage_client = storage.Client(credentials=self.credentials)

    def upload_file(self, bucket_name, source_file_name, destination_file_name):
        """Uploads a file to the bucket."""
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_file_name)
        blob.upload_from_filename(source_file_name)
        if not blob.exists():
            raise Exception('Upload file to google cloud file')
        return True
