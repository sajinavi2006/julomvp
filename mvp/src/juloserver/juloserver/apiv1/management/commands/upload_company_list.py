import json
import logging
import os
import shutil
import sys
import tempfile

import boto3
from django.conf import settings
from django.core.management.base import BaseCommand

from ...data import DropDownData, DropDownDataType

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'upload zipped company list to s3'

    def handle(self, *args, **options):

        ddd = DropDownData(DropDownDataType.COMPANY)
        version = ddd._select_version()
        company_list = ddd._select_data()
        logger.info(
            {'status': 'got_company_list', 'version': version, 'list_count': len(company_list)}
        )

        data = {'version': version, 'list': company_list}

        tempdir = os.path.abspath(tempfile.mkdtemp())
        try:

            rawdir = os.path.join(tempdir, 'raw')
            os.makedirs(rawdir)
            jsonfile_path = os.path.join(rawdir, 'company_list_%s.json' % version)
            logger.info({'action': 'creating_json_file', 'path': jsonfile_path})
            with open(jsonfile_path, 'w') as f:
                f.write(json.dumps(data, indent=2))

            zipfile_path_no_ext = os.path.join(tempdir, 'company_list_%s' % version)
            zipfile_path = shutil.make_archive(zipfile_path_no_ext, 'zip', rawdir)
            logger.info({'status': 'zip_file_created', 'path': zipfile_path})

            s3_client = boto3.resource(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
            bucket_name = 'julopublic'
            bucket = s3_client.Bucket(bucket_name)

            key_path = os.path.basename(zipfile_path)
            bucket.upload_file(zipfile_path, key_path)
            logger.info({'status': 'uploaded', 'bucket': bucket_name, 'key': key_path})

            object_acl = s3_client.ObjectAcl(bucket_name, os.path.basename(zipfile_path))
            object_acl.put(ACL='public-read')
            logger.info(
                {
                    'status': 'made_public',
                    'bucket': object_acl.bucket_name,
                    'key': object_acl.object_key,
                }
            )

        finally:
            if os.path.isdir(tempdir):
                logger.info({'action': 'deleting', 'dir': tempdir})
                shutil.rmtree(tempdir)

        self.stdout.write(self.style.SUCCESS('Success'))
