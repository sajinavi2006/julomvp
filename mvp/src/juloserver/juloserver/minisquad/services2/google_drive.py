import re
import io
import os
import pickle
import logging
import json
import requests

from django.utils import timezone
from django.conf import settings
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from juloserver.julo.clients import get_julo_sentry_client
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import timedelta
from juloserver.julo.models import TokenRefreshStorage
from juloserver.julo.constants import TokenRefreshNameConst, TokenRefreshScopeConst


def get_data_google_drive_api_client():
    return GoogleDriveAPI(
        creds_path=settings.GOOGLE_DRIVE_CREDENTIALS_PATH,
        token_from_infra=settings.GOOGLE_DRIVE_TOKEN,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        token_name=TokenRefreshNameConst.DATA_GOOGLE_ACCOUNT,
    )


def get_finance_google_drive_api_client():
    return GoogleDriveAPI(
        creds_path=settings.ENGINEER_GOOGLE_DRIVE_CREDENTIALS_PATH,
        token_from_infra=settings.ENGINEER_GOOGLE_DRIVE_TOKEN,
        client_id=settings.ENGINEER_GOOGLE_CLIENT_ID,
        client_secret=settings.ENGINEER_GOOGLE_CLIENT_SECRET,
        token_name=TokenRefreshNameConst.REPAYMENT_GOOGLE_ACCOUNT,
    )


def get_partnership_google_drive_api_client():
    return GoogleDriveAPI(
        creds_path=settings.PARTNERSHIP_GOOGLE_DRIVE_CREDENTIALS_PATH,
        token_from_infra=settings.PARTNERSHIP_GOOGLE_DRIVE_TOKEN,
        client_id=settings.PARTNERSHIP_GOOGLE_CLIENT_ID,
        client_secret=settings.PARTNERSHIP_GOOGLE_CLIENT_SECRET,
        token_name=TokenRefreshNameConst.PARTNERSHIP_GOOGLE_ACCOUNT,
    )


def get_collection_google_drive_api_client():
    return GoogleDriveAPI(
        creds_path=settings.COLLECTION_GOOGLE_DRIVE_CREDENTIALS_PATH,
        token_from_infra=settings.COLLECTION_GOOGLE_DRIVE_TOKEN,
        client_id=settings.COLLECTION_GOOGLE_CLIENT_ID,
        client_secret=settings.COLLECTION_GOOGLE_CLIENT_SECRET,
        token_name=TokenRefreshNameConst.COLLECTION_GOOGLE_ACCOUNT,
    )


class GoogleDriveAPI():
    # reference: https://developers.google.com/drive/api/quickstart/python
    def __init__(self, creds_path, token_from_infra, client_id, client_secret, token_name):
        self.creds_path = creds_path
        self.token_name = token_name
        self.token_from_infra = token_from_infra
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = ["https://www.googleapis.com/auth/drive"]
        self.creds = self.get_credential()
        self.service = build('drive', 'v3', credentials=self.creds)
        self.logger = logging.getLogger(__name__)
        self.today = timezone.localtime(timezone.now()).date()
        self.formatted_date = self.today.strftime('%Y-%m-%d')

    def get_credential(self):
        creds = None
        token_refresh_gdrive = TokenRefreshStorage.objects.filter(
            name=self.token_name,
            scope=TokenRefreshScopeConst.GOOGLE_DRIVE,
        ).last()
        if not token_refresh_gdrive:
            token_data = self.token_from_infra.replace("'", "\"")
            token_data = json.loads(token_data)
            token_refresh_gdrive = TokenRefreshStorage.objects.create(
                name=self.token_name,
                scope=TokenRefreshScopeConst.GOOGLE_DRIVE,
                token=token_data,
            )
        # inject client_id and secret to token
        token_data = token_refresh_gdrive.token
        token_data["client_id"] = self.client_id
        token_data["client_secret"] = self.client_secret
        creds = Credentials.from_authorized_user_info(token_data, self.scopes)
        # handle when token invalid or not exist
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token_data = json.loads(creds.to_json())
                del token_data["client_id"]
                del token_data["client_secret"]
                token_refresh_gdrive.token = token_data
                token_refresh_gdrive.save(update_fields=["token"])
            else:
                # run manually only on local to get token for the first time
                flow = InstalledAppFlow.from_client_secrets_file(self.creds_path, self.scopes)
                creds = flow.run_local_server(port=0)

        return creds

    def make_request_file_list(self, query, type):
        file_or_folder_id = None
        request = self.service.files().list(q=query).execute()
        files_or_folders = request.get('files', [])
        if files_or_folders:
            file_or_folder_id = files_or_folders[0]['id']
        else:
            self.logger.info({
                'action': 'make_request_file_list',
                'type': type,
                'message': 'No {} found.'.format(type)
            })

        return file_or_folder_id

    def download_by_file_id(self, file_id):
        try:
            request = self.service.files().get_media(fileId=file_id)
            response = request.execute()
            download_path = '/media/' + self.formatted_date + '.csv'
            with open(download_path, 'wb') as f:
                f.write(response)
            return download_path
        except Exception as err:
            self.logger.error({
                'action': 'download_by_file_id',
                'message': str(err)
            })
            return None

    def find_file_on_folder_by_id(self, folder_id):
        file_id = None
        try:
            filename = self.formatted_date + '.csv'
            query_search_file = f"'{folder_id}' in parents and name='{filename}'"
            file_id = self.make_request_file_list(query_search_file, 'file')
            if not file_id:
                self.logger.info({
                    'action': 'find_file_on_folder_by_id',
                    'message': 'There no file with name {} on folder_id {}'.format(
                    filename, folder_id)
                })
                return
            # passing the file id and download it to local
            return self.download_by_file_id(file_id)
        except Exception as err:
            self.logger.error({
                'action': 'find_file_on_folder_by_id',
                'message': str(err)
            })
            get_julo_sentry_client().captureException()
            return None

    def find_file_or_folder_by_name(self, filename, parent_folder_id=None, is_folder=False):
        try:
            query_search_file = "name='{}'".format(filename)
            if parent_folder_id:
                query_search_file = "{} and '{}' in parents".format(
                    query_search_file, parent_folder_id
                )
            if is_folder:
                query_search_file = "{} and mimeType = 'application/vnd.google-apps.folder'".format(
                    query_search_file
                )
            else:
                query_search_file = (
                    "{} and mimeType != 'application/vnd.google-apps.folder'".format(
                        query_search_file
                    )
                )
            folder_id = self.make_request_file_list(query_search_file, 'file')
            if not folder_id:
                self.logger.info(
                    {
                        'action': 'find_folder_by_name',
                        'message': 'There no folder with name {}'.format(filename),
                    }
                )
                return
            # passing the file id and download it to local
            return folder_id
        except Exception as err:
            self.logger.error({'action': 'find_folder_by_name', 'message': str(err)})
            get_julo_sentry_client().captureException()
            return None

    def get_data_by_file_id(self, file_id):
        try:
            request = self.service.files().get_media(fileId=file_id)
            response = request.execute()
            return response
        except Exception as err:
            self.logger.error({'action': 'download_data_by_file_id', 'message': str(err)})
            get_julo_sentry_client().captureException()
            return None

    def upload_to_folder_id(self, byte, mime_type, dest_folder_id, file_name):
        file_metadata = {"name": file_name, "parents": [dest_folder_id]}
        media = MediaIoBaseUpload(byte, mimetype=mime_type)
        file = (
            self.service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        )

        return file.get("id")

    def delete_file_by_file_id(self, file_id):
        body_value = {'trashed': True}
        file = self.service.files().update(fileId=file_id, body=body_value).execute()

        return file.get("id")

    def download_restricted_google_drive_file(self, file_id, file_path):
        """Download a file from Google Drive using the Drive API with a OAUTH account."""
        try:
            request = self.service.files().get_media(fileId=file_id)
            with io.FileIO(file_path, 'wb') as file_stream:
                downloader = MediaIoBaseDownload(file_stream, request)
                done = False
                while not done:
                    # Download in chunks
                    status, done = downloader.next_chunk()

        except Exception as err:
            self.logger.error(
                {
                    'action': 'download_restricted_google_drive_file',
                    'file_id': file_id,
                    'message': str(err),
                }
            )
            get_julo_sentry_client().captureException()

    def get_file_metadata(self, file_id):
        """Retrieve file metadata (such as filename and MIME type) from Google Drive."""
        file_metadata = (
            self.service.files().get(fileId=file_id, fields='name, mimeType, size').execute()
        )
        file_name = file_metadata.get('name')
        mime_type = file_metadata.get('mimeType')
        file_size = int(file_metadata.get('size', 0))

        return file_name, mime_type, file_size

    def create_folder_on_parent_folder_id(self, parent_folder_id: str, folder_name: str) -> str:
        """Create new folder on parent folder id, and return new folder id itself"""
        query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and '{parent_folder_id}' in parents and trashed=false"
        results = (
            self.service.files()
            .list(q=query, spaces='drive', fields='nextPageToken, files(id, name)')
            .execute()
        )
        folder = results.get('files', [])
        if not folder:
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_folder_id],
            }
            folder = self.service.files().create(body=file_metadata, fields='id').execute()
            return folder.get('id')
        else:
            return folder[0]['id']


def get_google_drive_file_id(url):
    """Fetch file id from the URL"""
    if "drive.google" not in url:
        raise Exception("url must be google drive")
    regex = "https://drive.google.com/file/d/(.*?)/(.*?)"
    file_id = re.search(regex, url)
    if not file_id:
        raise Exception("Google Drive URL is not valid: {}".format(url))
    file_id = file_id[1]
    return file_id
