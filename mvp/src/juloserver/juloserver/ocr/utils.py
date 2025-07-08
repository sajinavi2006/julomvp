import os
from builtins import str
from os.path import join

from django.conf import settings


def text_upload_handle_media(content, file_path, file_name):
    generate_dir = join(settings.MEDIA_ROOT, file_path)
    if not os.path.exists(generate_dir):
        os.makedirs(generate_dir)

    local_file_path = join(generate_dir, file_name)
    remote_file_path = join(file_path, file_name)

    # create file from uploaded
    with open(local_file_path, 'w') as destination:
        destination.write(str(content))

    return local_file_path, remote_file_path


def remove_local_file(local_path):
    if os.path.isfile(local_path):
        os.remove(local_path)
