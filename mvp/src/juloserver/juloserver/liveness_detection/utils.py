import base64
import json

from cryptography.fernet import Fernet
from django.conf import settings


def convert_image_to_base64(image) -> str:
    image.seek(0)  # need to read file from the beginning
    image_byte = image.file.read()

    return base64.b64encode(image_byte).decode('utf-8')


def encrypt_android_app_license(data):
    data = json.dumps(data)
    fernet = Fernet(settings.LIVENESS_LICENSE_KEY)
    return fernet.encrypt(data.encode()).decode()


def get_max_count(collection_count, collection):
    max_count = 0
    max_item = collection[0]
    for item in collection:
        if collection_count[item]['count'] > max_count:
            max_count = collection_count[item]['count']
            max_item = item

    return max_count, max_item
