
from datetime import  timedelta
import datetime
import os
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from celery.task import task
from django.db import transaction
from django.db.models import Q
import xlwt
from juloserver.account.constants import FeatureNameConst
from juloserver.account.models import Account, AccountLookup
from juloserver.account_payment.models import AccountPayment
from juloserver.collection_field_automation.models import FieldAssignment
from juloserver.collection_vendor.celery_progress import ProgressRecorder
from juloserver.collection_vendor.task import process_expire_bulk_download_cache
from juloserver.fdc.files import TempDir
from juloserver.julo.models import FeatureSetting
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.utils import get_oss_presigned_url, upload_file_to_oss
from juloserver.minisquad.constants import DialerTaskStatus
from juloserver.minisquad.models import (BulkVendorRecordingFileCache, DialerTask, SentToDialer,)
from juloserver.sdk.services import xls_to_dict


@task(queue="collection_normal")
def bulk_assign_account_to_agent_field(dialer_task_id,data_formated):
    dialer_task = DialerTask.objects.get(pk=dialer_task_id)
    dialer_task.update_safely(
        status=DialerTaskStatus.PROCESSED,
    )
    progress_recorder = ProgressRecorder(
        task_id=bulk_assign_account_to_agent_field.request.id
    )
    processed_count=0
    data_xls = data_formated['list_sent_to_dialer']
    data_for_insert = []
    data_for_update = []
    invalid_data = []
    today = timezone.localtime(timezone.now()).date()
    for idx, row_data in enumerate(data_xls):
        index = idx + 1
        if 'agent username' not in row_data:
            continue

        agent_username = row_data['agent username']
        if not agent_username:
            continue

        agent_user = User.objects.filter(
            username=agent_username.lower()).last()
        if not agent_user:
            progress_recorder.update_status("FAILURE",'agent dengan username {} tidak ada di database'.format(
                        agent_username.lower()
                    ))
            
            continue

        account = Account.objects.get_or_none(
            pk=row_data['account id'])
        if not account:
            continue

        expiry_date = None
        if 'expiry date' in row_data:
            try:
                expiry_date = datetime.datetime.strptime(
                    row_data['expiry date'], '%Y-%m-%d')
            except ValueError:       
                progress_recorder.update_status("FAILURE",'Format expiry date {} salah'.format(row_data['expiry date']))

        check_existing_agent = FieldAssignment.objects.filter(
            Q(expiry_date__gte=today) | Q(expiry_date__isnull=True),
            account=account,
        ).last()
        if check_existing_agent:
            data_for_update.append(
                dict(
                    field_assignment_id=check_existing_agent.id,
                    assign_date=today,
                    new_agent_id=agent_user.id,
                    expiry_date=expiry_date
                )
            )
        else:
            data_for_insert.append(
                dict(
                    agent=agent_user,
                    account=account,
                    expiry_date=expiry_date,
                    assign_date=today,
                )
            )

    if len(invalid_data) > 0:
        progress_recorder.update_status("FAILURE",'Upload gagal beberapa data tidak memenuhi validasi')

    if len(data_for_update) == 0 and len(data_for_insert) == 0:
        progress_recorder.update_status("FAILURE",'Assign account ke agent field gagal, mohon periksa kembali excelnya')
    
    total_process = len(data_for_insert) + len(data_for_update)
    today = timezone.localtime(timezone.now())

    with transaction.atomic():
        if len(data_for_insert) > 0 :
            for agent_field_assignment in data_for_insert:
                processed_count += 1
                progress_recorder.set_progress(processed_count, total_process)
                FieldAssignment.objects.create(
                    agent=agent_field_assignment['agent'],
                    account=agent_field_assignment['account'],
                    expiry_date=agent_field_assignment['expiry_date'],
                    assign_date=agent_field_assignment['assign_date'],
                )

        if len(data_for_update) > 0:
            for agent_field_assignment in data_for_update:
                processed_count += 1
                progress_recorder.set_progress(processed_count, total_process)
                FieldAssignment.objects.filter(
                    pk=agent_field_assignment['field_assignment_id']).update(
                    agent_id=agent_field_assignment['new_agent_id'],
                    expiry_date=agent_field_assignment['expiry_date'],
                    assign_date=agent_field_assignment['assign_date'],
                    udate=today
                )


@task(queue="collection_normal")
def bulk_change_agent_field_ownership(new_agent_field_assignments):
    today = timezone.localtime(timezone.now())
    with transaction.atomic():
        for agent_field_assignment in new_agent_field_assignments:
            FieldAssignment.objects.filter(
                pk=agent_field_assignment['field_assignment_id']).update(
                agent_id=agent_field_assignment['new_agent_id'],
                expiry_date=agent_field_assignment['expiry_date'],
                assign_date=agent_field_assignment['assign_date'],
                udate=today
            )

                
@task(queue="collection_normal")
def do_delete_excel(excel_file_name):
    filename =  str(excel_file_name) + ".xls"
    excel_filepath = os.path.join(settings.BASE_DIR + '/media/',filename)
    if os.path.isfile(excel_filepath):
        os.remove(excel_filepath)


@task(queue="collection_normal")
def process_download_excel_files(dialer_task_id,eligible_account_ids):
    processed_count=0
    progress_recorder = ProgressRecorder(
        task_id=process_download_excel_files.request.id
    )
    dialer_task = DialerTask.objects.get(pk=dialer_task_id)
    dialer_task.update_safely(
        status=DialerTaskStatus.PROCESSED,
    )
    fpath = settings.BASE_DIR + '/media/'
    if not os.path.isdir(fpath):
        os.mkdir(fpath)
        
    excel_file_name = "field_collection_automation_{}.xls".format(timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M%S"))
    excel_filepath = os.path.join(settings.BASE_DIR + '/media/', excel_file_name)
    total_process = len(eligible_account_ids)
    wb = xlwt.Workbook(style_compression=2)
    ws = wb.add_sheet("list_sent_to_dialer", cell_overwrite_ok=True)
    font_style = xlwt.XFStyle()
    font_style.font.bold = True
    row_num = 0
    columns = ('Account Id',
            'Agent Username',
            'Expiry Date',
            'Area',
            'Overdue Amount'
            )

    column_size = list(range(len(columns)))
    for col_num in column_size:
        ws.write(row_num, col_num, columns[col_num], font_style)

    for account_id in list(eligible_account_ids):
        processed_count += 1
        progress_recorder.set_progress(processed_count, total_process,
                                       str(excel_file_name).replace('.xls',''))
        row_num += 1
        account = Account.objects.get_or_none(pk=account_id)
        if not account:
            continue

        application = account.application_set.last()
        
        if not application:
            continue
        
        data = (
            account_id, '', '', application.address_kelurahan,
            account.get_total_overdue_amount() or 0
        )
        font_style = xlwt.XFStyle()
        data_size = list(range(len(data)))
        for data_slice in data_size:
            ws.write(row_num, data_slice, data[data_slice], font_style)

    wb.save(excel_filepath)
    
    
@task(queue="collection_normal")
def process_upload_excel_files(dialer_task_id,data_formated):
    processed_count=0
    
    data_xls = data_formated['list_sent_to_dialer']
    progress_recorder = ProgressRecorder(
        task_id=process_upload_excel_files.request.id
    )
    dialer_task = DialerTask.objects.get(pk=dialer_task_id)
    dialer_task.update_safely(
        status=DialerTaskStatus.PROCESSED,
    )
    data_for_insert = []
    data_for_update = []
    invalid_data = []
    today = timezone.localtime(timezone.now()).date()
    total_process = len(enumerate(data_formated))
    for idx, row_data in enumerate(data_xls):
        index = idx + 1
        processed_count += 1
        progress_recorder.set_progress(processed_count, total_process)
        if 'agent username' not in row_data:
            continue

        agent_username = row_data['agent username']
        if not agent_username:
            continue

        agent_user = User.objects.filter(
            username=agent_username.lower()).last()
        if not agent_user:
            invalid_data.append(
                dict(
                    row_number=index,
                    account_id=row_data['account id'],
                    error_message='agent dengan username {} tidak ada di database'.format(
                        agent_username.lower()
                    )
                )
            )
            continue

        account = Account.objects.get_or_none(
            pk=row_data['account id'])
        if not account:
            continue

        expiry_date = None
        if 'expiry date' in row_data:
            try:
                expiry_date = datetime.strptime(
                    row_data['expiry date'], '%Y-%m-%d')
            except ValueError:
                invalid_data.append(
                    dict(
                        row_number=index,
                        account_id=row_data['account id'],
                        error_message='Format expiry date {} salah'.format(row_data['expiry date'])
                    )
                )
                continue

        check_existing_agent = FieldAssignment.objects.filter(
            Q(expiry_date__gte=today) | Q(expiry_date__isnull=True),
            account=account,
        ).last()
        if check_existing_agent:
            data_for_update.append(
                dict(
                    field_assignment_id=check_existing_agent.id,
                    assign_date=today,
                    new_agent_id=agent_user.id,
                    expiry_date=expiry_date
                )
            )
        else:
            data_for_insert.append(
                FieldAssignment(
                    agent=agent_user,
                    account=account,
                    expiry_date=expiry_date,
                    assign_date=today,
                )
            )


@task(queue="collection_normal")
def process_unassignment_field_assignment(account_payment_id):
    account_payment = AccountPayment.objects.get_or_none(
        pk=account_payment_id)
    today = timezone.localtime(timezone.now()).date()

    if not account_payment:
        return
    FieldAssignment.objects.filter(
        Q(expiry_date__gte=today) | Q(expiry_date__isnull=True),
        account=account_payment.account,
    ).update(expiry_date=today, udate=timezone.localtime(timezone.now()))
