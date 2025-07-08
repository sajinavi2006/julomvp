import os
import base64
from django.conf import settings
from juloserver.minisquad.constants import BTTCExperiment


def file_to_base64(filename):
    with open(filename, "rb") as f:
        data = f.read()

    data_w = bytes(data)
    data_t = base64.b64encode(data_w)
    return data_t


def delete_local_file_after_upload(recording_file_path):
    # delete file from juloserver
    if os.path.exists(recording_file_path):
        os.remove(recording_file_path)


def extract_bucket_name_dialer(task_name: str):
    setting_env = settings.ENVIRONMENT.upper()
    bucket_name_extracted = task_name.split('-')
    index = 0
    if setting_env != 'PROD':
        index = 1
    bucket_name = bucket_name_extracted[index]
    if bucket_name not in ['JULO_T', 'JTURBO_T']:
        return bucket_name
    return '{}-{}'.format(bucket_name, bucket_name_extracted[index + 1])


def extract_bucket_name_dialer_bttc(task_name: str) -> str:
    values = ['A', 'B', 'C', 'D']
    based_bucket_names = list(BTTCExperiment.BUCKET_NAMES_CURRENT_MAPPING.values())
    based_bucket_names.append(BTTCExperiment.BASED_T0_NAME)

    for based_bucket_name in based_bucket_names:
        for value in values:
            bttc_bucket_name = based_bucket_name.format(value)
            if bttc_bucket_name in task_name:
                return bttc_bucket_name

    return ''
