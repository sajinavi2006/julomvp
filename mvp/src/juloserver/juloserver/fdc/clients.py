import logging
import os
from builtins import object

import pysftp
import requests
from django.conf import settings

from .exceptions import FDCServerUnavailableException

logger = logging.getLogger(__name__)


def get_julo_fdc_ftp_client():
    return FDCFTPClient(
        settings.FDC_SFTP_HOST,
        settings.FDC_SFTP_USERNAME,
        settings.FDC_SFTP_PASSWORD,
        settings.FDC_SFTP_PROXY_PORT,
    )


def get_julo_fdc_client():
    return FDCClient(
        settings.FDC_API_USERNAME, settings.FDC_API_PASSWORD, settings.FDC_API_BASE_URL
    )


class FDCFTPClient(object):
    OUTDATED_LOANS_FILENAME = "outdated_data_810069"
    STATISTIC_FDC_FILENAME = "statistic_file_810069.json"
    STATISTIC_LOAN_FILENAME = "statistic_loan_810069.json"

    OUTPUT_PATH = "/out/"
    INPUT_PATH = "/in/"

    def __init__(self, host, username, password, port):
        self.host = host
        self.username = username
        self.password = password
        self.port = int(port)

    def get_fdc_ftp_connection(self):
        cnopts = pysftp.CnOpts()
        cnopts.hostkeys = None

        return pysftp.Connection(
            host=self.host,
            username=self.username,
            password=self.password,
            port=self.port,
            cnopts=cnopts,
        )

    def is_fdc_result_exists(self, output_result_filename):
        remote_path = self.OUTPUT_PATH + output_result_filename

        with self.get_fdc_ftp_connection() as connection:
            logger.info({"action": "checking", "remote_path": remote_path, "host": self.host})
            return connection.isfile(remote_path)

    def is_outdated_loans_file_exist(self):
        output_filename_zip = "%s.zip" % self.OUTDATED_LOANS_FILENAME
        remote_path = self.OUTPUT_PATH + output_filename_zip

        with self.get_fdc_ftp_connection() as connection:
            logger.info({"action": "checking", "remote_path": remote_path, "host": self.host})
            return connection.isfile(remote_path)

    def is_statistic_json_file_exists(self):
        remote_path = self.OUTPUT_PATH + self.STATISTIC_FDC_FILENAME

        with self.get_fdc_ftp_connection() as connection:
            logger.info({"action": "checking", "remote_path": remote_path, "host": self.host})
            return connection.isfile(remote_path)

    def is_statistic_loan_json_file_exists(self):
        remote_path = self.OUTPUT_PATH + self.STATISTIC_LOAN_FILENAME

        with self.get_fdc_ftp_connection() as connection:
            logger.info({"action": "checking", "remote_path": remote_path, "host": self.host})
            return connection.isfile(remote_path)

    def get_outdated_loans_file(self, dirpath):
        output_filename_zip = "%s.zip" % self.OUTDATED_LOANS_FILENAME
        remote_path = self.OUTPUT_PATH + output_filename_zip

        with self.get_fdc_ftp_connection() as connection:
            local_path = os.path.join(dirpath, output_filename_zip)
            logger.info(
                {
                    "action": "downloading",
                    "remote_path": remote_path,
                    "local_path": local_path,
                    "host": self.host,
                }
            )
            connection.get(remote_path, local_path)
            return local_path

    def get_statistic_fdc_file(self, dirpath):
        output_filename = self.STATISTIC_FDC_FILENAME
        remote_path = self.OUTPUT_PATH + output_filename

        with self.get_fdc_ftp_connection() as connection:
            local_path = os.path.join(dirpath, output_filename)
            logger.info(
                {
                    "action": "downloading",
                    "remote_path": remote_path,
                    "local_path": local_path,
                    "host": self.host,
                }
            )
            connection.get(remote_path, local_path)
            return local_path

    def get_statistic_loan_fdc_file(self, dirpath):
        output_filename = self.STATISTIC_LOAN_FILENAME
        remote_path = self.OUTPUT_PATH + output_filename

        with self.get_fdc_ftp_connection() as connection:
            local_path = os.path.join(dirpath, output_filename)
            logger.info(
                {
                    "action": "downloading",
                    "remote_path": remote_path,
                    "local_path": local_path,
                    "host": self.host,
                }
            )
            connection.get(remote_path, local_path)
            return local_path

    def get_upload_errors_file(self, dirpath, output_filename):
        remote_path = self.OUTPUT_PATH + output_filename

        with self.get_fdc_ftp_connection() as connection:
            local_path = os.path.join(dirpath, output_filename)
            try:
                logger.info(
                    {
                        "action": "downloading",
                        "remote_path": remote_path,
                        "local_path": local_path,
                        "host": self.host,
                    }
                )
                connection.get(remote_path, local_path)
            except Exception as e:
                logger.info(
                    {
                        "action": "downloading",
                        "remote_path": remote_path,
                        "local_path": local_path,
                        "host": self.host,
                        "error": e,
                    }
                )
                return ''

            return local_path

    def put_fdc_data(self, filepath, filename):
        remote_path = self.INPUT_PATH + filename

        with self.get_fdc_ftp_connection() as connection:
            logger.info(
                {
                    "action": "uploading",
                    "filename": filename,
                    "remote_path": remote_path,
                    "local_path": filepath,
                    "host": self.host,
                }
            )
            connection.put(filepath, remote_path)


class FDCClient(object):
    def __init__(self, username, password, base_url):
        self.username = username
        self.password = password
        self.base_url = base_url

    def get_fdc_inquiry_data(self, nik, reason, reffid=None):
        url = self.base_url + '/api/v5.2/Inquiry?id=%s&reason=%s' % (nik, reason)
        if reffid:
            url += '&reffid={}'.format(reffid)
        response = requests.get(url, auth=(self.username, self.password))
        if response.status_code in {503, 502, 504, 599}:
            raise FDCServerUnavailableException()
        return response
