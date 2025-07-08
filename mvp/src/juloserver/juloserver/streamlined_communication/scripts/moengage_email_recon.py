from datetime import datetime
import os
import pandas as pd

from juloserver.email_delivery.constants import EmailStatusMapping
from juloserver.email_delivery.utils import email_status_prioritization
from juloserver.julo.models import EmailHistory
from juloserver.streamlined_communication.admin import EmailHistoryAdminSerializer


def update_email_history(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f'File "{file_path}" does not exist')

    data = load_data(file_path)
    success_count, error_count, warning_count, report_data = process_upload_data(data)
    generate_report(file_path, success_count, error_count, warning_count, report_data)


def load_data(file_path):
    column_types = {
        'me_email_id': str,
        'status': str,
        'campaign_id': str,
        'template_code': str,
        'to_email': str,
        'application_id': str,
        'customer_id': str,
    }

    if file_path.endswith('.csv'):
        return pd.read_csv(file_path, dtype=column_types)
    elif file_path.endswith('.xls') or file_path.endswith('.xlsx'):
        return pd.read_excel(file_path, dtype=column_types)
    else:
        raise ValueError('Invalid file format. Only .csv, .xls, and .xlsx are supported.')


def process_upload_data(data):
    success_count = 0
    error_count = 0
    warning_count = 0
    error_warning_rows = []

    for index, row in data.iterrows():
        row_dict = row.to_dict()

        if is_empty(row, 'application_id') and is_empty(row, 'customer_id'):
            add_error(row_dict, 'Both Application ID and Customer ID are empty.')
            error_warning_rows.append(row_dict)
            error_count += 1
            continue

        serializer = EmailHistoryAdminSerializer(data=row_dict)
        if not serializer.is_valid():
            add_error(row_dict, f"Validation errors: {serializer.errors}.")
            error_warning_rows.append(row_dict)
            error_count += 1
            continue

        try:
            email_histories = get_email_histories(row)
            if email_histories.count() == 1:
                handle_single_email_history(email_histories.first(), row, row_dict)
                success_count += 1
            elif email_histories.count() > 1:
                handle_multiple_email_histories(email_histories, row, row_dict)
                error_warning_rows.append(row_dict)
                warning_count += 1
            else:
                add_error(row_dict, 'Record not found in database.')
                error_warning_rows.append(row_dict)
                error_count += 1
        except Exception as e:
            add_error(row_dict, f'Unhandled exception. Error details: {str(e)}.')
            error_warning_rows.append(row_dict)
            error_count += 1

    data_frame_columns = [
        'me_email_id',
        'status',
        'campaign_id',
        'template_code',
        'to_email',
        'application_id',
        'customer_id',
        'Error Reason',
        'Warning Reason',
    ]

    error_warning_data = (
        pd.DataFrame(error_warning_rows, columns=data_frame_columns) if error_warning_rows else None
    )
    return success_count, error_count, warning_count, error_warning_data


def is_empty(row, column_name):
    return pd.isna(row[column_name]) or row[column_name].strip() == ''


def add_error(row_dict, message):
    row_dict['Error Reason'] = message
    row_dict['Warning Reason'] = ''


def add_warning(row_dict, message):
    row_dict['Warning Reason'] = message
    row_dict['Error Reason'] = ''


def get_email_histories(row):
    if not is_empty(row, 'application_id'):
        return EmailHistory.objects.filter(
            application_id=row['application_id'],
            template_code=row['template_code'],
            to_email=row['to_email'],
            campaign_id=row['campaign_id'],
        )
    else:
        return EmailHistory.objects.filter(
            customer_id=row['customer_id'],
            template_code=row['template_code'],
            to_email=row['to_email'],
            campaign_id=row['campaign_id'],
        )


def handle_single_email_history(email_history, row, row_dict):
    moengage_status = get_moengage_status(row)
    current_status = email_history.status
    processed_status = email_status_prioritization(current_status, moengage_status)
    email_history.status = processed_status
    email_history.save()


def handle_multiple_email_histories(email_histories, row, row_dict):
    moengage_status = get_moengage_status(row)
    statuses = [email_history.status for email_history in email_histories]
    new_status_value = EmailStatusMapping['MoEngageStreamPriority'][moengage_status]

    highest_status = max(
        statuses, key=lambda status: EmailStatusMapping['MoEngageStreamPriority'][status]
    )
    highest_status_value = EmailStatusMapping['MoEngageStreamPriority'][highest_status]

    if new_status_value > highest_status_value:
        update_and_delete_rest(email_histories, moengage_status)
        add_warning(row_dict, f'Updated one record to status {moengage_status} and deleted others.')
    elif new_status_value <= highest_status_value:
        update_and_delete_rest(email_histories, highest_status)
        add_warning(
            row_dict, f'Retained highest priority status {highest_status} and deleted others.'
        )


def update_and_delete_rest(email_histories, status_to_set):
    updated = False
    for email_history in email_histories:
        if not updated:
            if email_history.status != status_to_set:
                email_history.status = status_to_set
                email_history.save()
            updated = True
        else:
            email_history.delete()


def get_moengage_status(row):
    moengage_stream_status_map = EmailStatusMapping['MoEngageStream']
    return moengage_stream_status_map.get(row['status'], 'unknown')


def generate_report(file_path, success_count, error_count, warning_count, report_data):
    if error_count > 0 or warning_count > 0:
        try:
            files_dir = os.path.dirname(file_path)
            os.makedirs(files_dir, exist_ok=True)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            error_file_path = os.path.join(files_dir, f'emailhistory_report_{timestamp}.csv')

            report_data.to_csv(error_file_path, index=False)

            print(
                f'Processed with errors. Success: {success_count}, Failed: {error_count}, Warnings: {warning_count}. Report saved to {error_file_path}'
            )
        except Exception as e:
            print(f'Error generating report CSV: {str(e)}')
    else:
        print(f'{success_count} records processed successfully with {warning_count} warnings!')
