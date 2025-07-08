from googleapiclient.discovery import build
from google.oauth2 import service_account


class GooglePlayIntegrityClient(object):

    def __init__(self, service_account_file, scopes=[], integrity_token=None):
        self.service_account_file = service_account_file
        self.scopes = scopes
        self.integrity_token = integrity_token

    def get_play_integrity_credentials(self):
        credentials = service_account.Credentials.from_service_account_file(
            self.service_account_file, scopes=self.scopes)
        return credentials
    
    def get_google_play_integrity_service(self):
        credentials = self.get_play_integrity_credentials()
        service = build('playintegrity', 'v1', credentials=credentials)
        latest_service_client = service.v1()
        return latest_service_client

    def decode_integrity_token(self):
        latest_service_client = self.get_google_play_integrity_service()
        body = {'integrityToken': str(self.integrity_token)}
        package_name = 'com.julofinance.juloapp'
        decode_request = latest_service_client.decodeIntegrityToken(packageName=package_name, body=body)
        try:
            payload_json = decode_request.execute()
        except Exception as e:
            return None, str(e)
        return payload_json, None
