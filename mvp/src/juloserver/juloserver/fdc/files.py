import csv
import json
import logging
import os
import shutil
import tempfile
from builtins import object, str
from zipfile import ZipFile
import pyminizip
import traceback

from juloserver.fdc.utils import create_fdc_filename

logger = logging.getLogger(__name__)


class TempDir(object):
    """Context manager managing random temporary directory"""

    def __init__(self, need_cleanup=True, dir=None):
        self.need_cleanup = need_cleanup
        self.path = ''
        self.dir = dir

    def __enter__(self):
        if not self.dir:
            self.path = os.path.abspath(tempfile.mkdtemp())
        else:
            self.path = os.path.abspath(tempfile.mkdtemp(dir=self.dir))
        logger.info({'action': 'creating', 'dir': self.path})
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if os.path.isdir(self.path) and self.need_cleanup:
            logger.info({'action': 'deleting', 'dir': self.path})
            shutil.rmtree(self.path)


def yield_outdated_loans_data_from_file(filepath):
    dirpath = os.path.dirname(filepath)
    with ZipFile(filepath, 'r') as zip_file:
        list_of_filenames = zip_file.namelist()
        for filename in list_of_filenames:
            if filename.endswith('.csv'):
                logger.info({'action': 'extracting', 'dir': filepath})
                extracted_folder = os.path.join(dirpath, filename)
                extracted_filepath = os.path.join(extracted_folder, filename)
                zip_file.extract(filename, path=extracted_folder)

    for row in yield_csv_file_fdc_data(extracted_filepath, delimiter=','):
        yield row


def yield_csv_file_fdc_data(filepath, delimiter):
    with open(filepath, 'r') as csv_file:
        csv_reader = csv.DictReader(csv_file, delimiter=delimiter)
        for row in csv_reader:
            yield row


def yield_statistic_fdc_data(filepath):
    with open(filepath) as json_file:
        statistic_data = json.load(json_file)
        for data in statistic_data:
            yield data


def store_loans_today_into_zipfile(
    dirpath,
    field_names,
    data,
    zip_password,
    count_today=0,
    count_of_record=0,
    current_row=0,
    list_of_zip=[],
    tempdir=None,
    config={},
):

    if current_row == count_of_record:
        return list_of_zip
    else:
        row_limit = config.get('row_limit')
        new_version_number = count_today + 1
        count_today = new_version_number

        filename = create_fdc_filename(new_version_number)
        csv_filename = filename + '.csv'
        zip_filename = filename + '.zip'

        try:
            zip_file, current_row = create_file_csv_and_zip(
                data,
                dirpath,
                csv_filename,
                filename,
                field_names,
                zip_password,
                current_row,
                row_limit=row_limit,
            )

            delete_csv_file(dirpath, csv_filename)
            file_uploads = {
                'count_today': count_today,
                'zip_file': zip_file,
                'zip_filename': zip_filename,
            }

            list_of_zip.append(file_uploads)
            logger.info(
                {
                    'message': '[Completed] creating file zip',
                    'zip_file_name': zip_filename,
                    'path_dir': str(zip_file),
                    'count_today': count_today,
                    'list_of_zip': str(list_of_zip),
                }
            )

            store_loans_today_into_zipfile(
                dirpath,
                field_names,
                data,
                zip_password,
                count_today,
                count_of_record,
                current_row,
                list_of_zip,
                config=config,
            )

        except OSError as error:
            logger.error(
                {
                    'message': 'OSError: {}'.format(str(error)),
                    'list_of_zip': str(list_of_zip),
                    'zip_filename': zip_filename,
                }
            )
            return list_of_zip

        except Exception as error:
            logger.error(
                {
                    'action': 'process zip failed',
                    'filename': filename,
                    'tempdir': tempdir,
                    'message': str(error),
                    'traceback': traceback.format_exc(),
                }
            )
            return list_of_zip


def create_file_csv_and_zip(
    data, dirpath, csv_filename, filename, field_names, zip_password, current_row, row_limit
):

    csv_filepath = os.path.join(dirpath, csv_filename)
    block_rows = []
    block_size = 100
    runner = 0
    count_row = 0

    for row in data:
        count_row += 1
        block_rows.append(row)
        runner += 1
        current_row += 1
        if runner == block_size:
            with open(csv_filepath, 'a') as csv_file:
                dict_writer = csv.DictWriter(csv_file, fieldnames=field_names, delimiter='|')
                dict_writer.writerows(block_rows)

            # reset
            runner = 0
            block_rows = []

        if row_limit == count_row:
            break

    if block_rows:
        with open(csv_filepath, 'a') as csv_file:
            dict_writer = csv.DictWriter(csv_file, fieldnames=field_names, delimiter='|')
            dict_writer.writerows(block_rows)

    zip_filename = filename + '.zip'
    zip_filepath = os.path.join(dirpath, zip_filename)
    compression_level = 1

    # zipfile set_password not working for writing, change into pyminizip
    pyminizip.compress(csv_filepath, None, zip_filepath, zip_password.encode(), compression_level)

    return zip_filepath, current_row


def parse_fdc_delivery_report(local_filepath):
    for data in yield_statistic_fdc_data(local_filepath):
        generated_at = data['generated_at']
        generated_date = generated_at[:10]
        generated_time = generated_at[13:30]
        generated_datetime = generated_date + ' ' + generated_time
        last_uploaded_sik = data['last_uploaded_sik']
        if last_uploaded_sik is None:
            last_uploaded_sik_datetime = None
        else:
            last_uploaded_sik_date = last_uploaded_sik[:10]
            last_uploaded_sik_time = last_uploaded_sik[13:30]
            last_uploaded_sik_datetime = last_uploaded_sik_date + ' ' + last_uploaded_sik_time

        percentage_updated = data['percentage']
        float_percentage_updated = float(percentage_updated[:-1]) / 100
        threshold = data['tresshold']
        float_threshold = float(threshold[:-1]) / 100

        fdc_delivery_report = dict(
            generated_at=generated_datetime,
            last_reporting_loan=data['last_reporting_loan'],
            last_uploaded_file_name=data['last_uploaded_sik_filename'],
            last_uploaded_sik=last_uploaded_sik_datetime,
            total_outstanding=data['tot_status_o'],
            total_paid_off=data['tot_status_l'],
            total_written_off=data['tot_status_w'],
            total_outstanding_outdated=data['not_updated_o'],
            percentage_updated=float_percentage_updated,
            threshold=float_threshold,
            access_status=str(data['access_status']),
        )

    return fdc_delivery_report


def parse_fdc_delivery_statistic(file_filepath, loan_filepath):
    from juloserver.fdc.services import reformat_generated_datetime_fdc

    file_data, loan_data = {}, {}

    for data in yield_statistic_fdc_data(file_filepath):
        generated_at = data['generated_at']
        generated_datetime = reformat_generated_datetime_fdc(generated_at)

        file_data = dict(
            statistic_file_generated_at=generated_datetime,
            status_file=list(data['status_file']),
        )

    for data in yield_statistic_fdc_data(loan_filepath):
        generated_at = data['generated_at']
        generated_datetime = reformat_generated_datetime_fdc(generated_at)

        loan_data = dict(
            statistic_loan_generated_at=generated_datetime,
            status_loan=list(data['status_loan']),
            quality_loan=list(data['quality_loan']),
        )

    fdc_delivery_statistic = file_data.copy()
    fdc_delivery_statistic.update(loan_data)

    return fdc_delivery_statistic


def parse_fdc_error_data(filename, local_filepath):
    fdc_error_data = []
    for row in yield_csv_file_fdc_data(local_filepath, delimiter='|'):
        if row['id_borrower'] in (None, ""):
            id_borrower = None
        else:
            id_borrower = row['id_borrower']
        if row['id_pinjaman'] in (None, ""):
            id_pinjaman = None
        else:
            id_pinjaman = row['id_pinjaman']
        data = dict(
            row_number=row['RowNo'],
            error=row['Errors'],
            id_borrower=id_borrower,
            id_pinjaman=id_pinjaman,
            filename=filename,
        )
        fdc_error_data.append(data)

    return fdc_error_data


def get_list_files(path):
    for file in os.listdir(path):
        if os.path.isfile(os.path.join(path, file)):
            yield file


def delete_csv_file(dirpath, csv_filename):
    csv_filepath = os.path.join(dirpath, csv_filename)
    if os.path.isfile(csv_filepath):
        # remove the file csv to make free disk
        logger.warning(
            {'message': 'Delete file CSV after create it as zip', 'csv_filepath': csv_filepath}
        )
        os.remove(csv_filepath)
