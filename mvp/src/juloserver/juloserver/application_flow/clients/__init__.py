import os
from django.conf import settings


def get_here_maps_client():
    from .here_maps import HEREMapsClient

    return HEREMapsClient(settings.HERE_GEO_CODING_API_KEY, settings.HERE_GEO_CODING_API_URL)


def get_google_play_integrity_token_file_path():
    token_file_path = settings.GOOGLE_PLAY_INTEGRITY_TOKEN_FILE_PATH
    file_name = 'credentials.json'
    token_file_dir = token_file_path.replace(file_name, '')
    if not os.path.exists(token_file_dir):
        os.mkdir(token_file_dir)
    if not os.path.exists(token_file_path) or os.path.getsize(token_file_path) <= 0:
        token_from_infra = settings.GOOGLE_PLAY_INTEGRITY_TOKEN
        token_from_infra = token_from_infra.replace("'", '"')
        with open(token_file_path, "w") as token_file:
            token_file.write(token_from_infra)
    return token_file_path

def get_google_play_integrity_client(integrity_token=None):
    from juloserver.application_flow.clients.google_play_integrity import \
        GooglePlayIntegrityClient

    scopes = ['https://www.googleapis.com/auth/playintegrity']
    token_file_path = get_google_play_integrity_token_file_path()
    return GooglePlayIntegrityClient(
        token_file_path, scopes, integrity_token)
