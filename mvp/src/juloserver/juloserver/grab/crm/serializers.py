import logging
import csv
import pandas as pd
import io
import datetime
from django.shortcuts import render
from django.db.utils import IntegrityError
from juloserver.grab.crm.forms import (
    GrabPromoCodeUploadFileForm,
    GrabFDCStuckApplicationUploadFileForm
)
from juloserver.julo.models import Application
from juloserver.grab.constants import ApplicationStatus
from django.db import transaction

from juloserver.portal.object import julo_login_required, julo_login_required_multigroup
from juloserver.grab.models import GrabPromoCode, FDCCheckManualApproval
from juloserver.grab.tasks import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.constants import WorkflowConst
from juloserver.moengage.utils import chunks
logger = logging.getLogger(__name__)


@julo_login_required
@julo_login_required_multigroup(['product_manager'])
def grab_promo_code_csv_upload_view(request):
    """
    Uploading CSV to add grab promo_code
    """
    template_name = 'object/grab_promo_code/promo_code_upload.html'
    logs = ""
    upload_form = GrabPromoCodeUploadFileForm
    ok_couter = 0
    nok_couter = 0

    def _render():
        """lamda func to reduce code"""
        return render(
            request,
            template_name,
            {
                'form': upload_form,
                'logs': logs,
                'ok': ok_couter,
                'nok': nok_couter,
            },
        )

    if request.method == 'POST':
        upload_form = upload_form(request.POST, request.FILES)
        if not upload_form.is_valid():
            for key in upload_form.errors:
                logs += upload_form.errors[key][0] + "\n"
                nok_couter += 1
            return _render()

        file_ = upload_form.cleaned_data['file_field']
        extension = file_.name.split('.')[-1]

        if extension != 'csv':
            nok_couter += 1
            logs = 'Please upload the correct file type: CSV'
            return _render()

        freader = io.StringIO(file_.read().decode('utf-8'))
        reader = csv.DictReader(freader, delimiter=',')
        error_msg = 'CSV format is not correct. '
        header_fields = ['promo_code', 'title', 'description', 'active_date', 'expire_date',
                         'image_url', 'blog_url', 'rule']
        header_not_exist = ''
        for header_field in header_fields:
            if header_field not in reader.fieldnames:
                header_not_exist += '{}, '.format(header_field)

        if header_not_exist:
            nok_couter += 1
            logs = error_msg + header_not_exist[:-2] + " not exists in header."
            return _render()

        promo_codes = set()
        for row in reader:
            if row['promo_code']:
                promo_codes.add(row["promo_code"])
        grab_promo_codes = GrabPromoCode.objects.filter(
            promo_code__in=promo_codes
        ).only("promo_code", "title", "active_date", "expire_date")
        grab_promo_code_dicts = dict()
        existing_promo_codes = ''
        for grab_promo_code in grab_promo_codes.iterator():
            existing_promo_codes += '{}, '.format(grab_promo_code)
            grab_promo_code_dicts[grab_promo_code.promo_code] = grab_promo_code
        if existing_promo_codes:
            nok_couter += 1
            logs = 'Promo codes - '+existing_promo_codes[:-2] + ' already exists.'
            return _render()

        freader.seek(0)
        reader.__init__(freader, delimiter=',')

        logs = ''
        promo_code_upload_list = []
        active_date = ''
        expire_date = ''
        date_format = '%d/%m/%Y'
        for idx, row in enumerate(reader, start=2):
            rules_list = []
            field_empty_error = ''
            row_id = ''
            validation_error = ''
            for i in range(8):
                row_id = idx
                non_value_columns = {5, 6}
                if i in non_value_columns:
                    continue

                if not list(row.items())[i][1]:
                    field_empty_error += list(row.items())[i][0]+', '
                if i == 0 and list(row.items())[i][1] and len(list(row.items())[i][1]) <= 2:
                    validation_error += list(row.items())[i][0] + ' should be greater than 2 character. '
                if i == 0 and list(row.items())[i][1] and not list(row.items())[i][1].isalnum():
                    validation_error += list(row.items())[i][0]+' should be alpha numeric. '
                if i == 1 and list(row.items())[i][1] and len(list(row.items())[i][1]) > 30:
                    validation_error += list(row.items())[i][0]+' should be not greater than 30 character. '
                if i == 3 and list(row.items())[i][1]:
                    date_string = list(row.items())[i][1]
                    try:
                        active_date = datetime.datetime.strptime(date_string, date_format).strftime(
                            "%Y-%m-%d"
                        )
                    except ValueError:
                        validation_error += "active_date - should be DD/MM/YYYY format. "
                if i == 4 and list(row.items())[i][1]:
                    date_string = list(row.items())[i][1]
                    try:
                        expire_date = datetime.datetime.strptime(date_string, date_format).strftime(
                            "%Y-%m-%d"
                        )
                        if active_date and expire_date < active_date:
                            validation_error += "expire_date - should not be less than active_date"

                    except ValueError:
                        validation_error += "expire_date - should be DD/MM/YYYY format."

                if i == 7 and list(row.items())[i][1]:
                    allowed_rules = {
                        GrabPromoCode.NEW_USER,
                        GrabPromoCode.EXISTING_USER_WITH_OUTSTANDING,
                        GrabPromoCode.EXISTING_USER_WITHOUT_OUTSTANDING,
                    }
                    error_msg = "rules - should contains comma separated integers {}".format(
                        allowed_rules
                    )

                    try:
                        rules = list(row.items())[i][1].split(",")
                        if len(rules) == 0:
                            validation_error += error_msg
                        else:
                            for rule in rules:
                                rule_strip = rule.strip()
                                if (not rule_strip.isdigit()) or (
                                    int(rule_strip) not in allowed_rules
                                ):
                                    validation_error += error_msg
                                    break
                                else:
                                    rules_list.append(rule_strip)
                    except ValueError:
                        validation_error += error_msg

            if field_empty_error and validation_error:
                logs += '\nRow num-{} - {} should not be empty. {}\n'.format(row_id,
                                                                             field_empty_error[:-2],
                                                                             validation_error)
            elif field_empty_error:
                logs += '\nRow num-{} - {} should not be empty. {}\n'.format(row_id,
                                                                             field_empty_error[:-2],
                                                                             validation_error)
            elif validation_error:
                logs += '\nRow num-{} - {}\n'.format(row_id,
                                                     validation_error)

            if not logs:
                data = GrabPromoCode(
                    promo_code=row['promo_code'],
                    title=row['title'],
                    description=row['description'],
                    active_date=active_date,
                    expire_date=expire_date,
                    image_url=row['image_url'],
                    blog_url=row['blog_url'],
                    rule=rules_list
                )
                promo_code_upload_list.append(data)

        if logs:
            nok_couter += 1
        if not logs:
            try:
                with transaction.atomic():
                    GrabPromoCode.objects.bulk_create(promo_code_upload_list, batch_size=30)
                    logs += "Promo codes added successfully \n"
                    ok_couter += 1
            except IntegrityError as e:
                logs += str(e)
                nok_couter += 1

        freader.close()
        return _render()
    else:
        return _render()


def validate_csv_rows(logs, data, row_id):
    validation_flag = False
    try:
        if str(data.status).strip().lower() not in {
            ApplicationStatus.APPROVE,
            ApplicationStatus.REJECT,
        }:
            validation_error = "status - should contains {} or {}".format(
            ApplicationStatus.APPROVE, ApplicationStatus.REJECT
            )
            logs += '\nRow num-{} - {}'.format(row_id, validation_error)
            validation_flag = True
    except  (AttributeError, TypeError) as e:
        logs += '\nRow num-{} status should not be empty'.format(row_id)
        validation_flag = True

    return logs, validation_flag

def check_app_id_exists_in_db(data, application_list, logs, row_id, validation_flag):
    if data.application_id not in application_list:
        if validation_flag:
            logs += ', '
        else:
            logs += '\nRow num-{} '.format(row_id)
        logs += 'application id {} not exists'.format(
            data.application_id
        )
    return logs

def validate_csv_file_and_get_app_ids_list(csv_file):
    row_id = 2
    logs = ''
    application_list = Application.objects.filter(
        id__in=set(csv_file['application_id'].tolist()),
        application_status_id = ApplicationStatusCodes.FORM_PARTIAL,
        workflow__name = WorkflowConst.GRAB
    ).values_list("id", flat=True)
    fdc_check_manual_approval_objects = []
    set_of_app_ids = set()
    for _, data in csv_file.iterrows():
        logs, validation_flag = validate_csv_rows(logs, data, row_id)

        logs = check_app_id_exists_in_db(
            data, application_list, logs, row_id, validation_flag
        )

        if not logs and data.application_id not in set_of_app_ids:
            set_of_app_ids.add(data.application_id)
            fdc_check_manual_approval_objects.append(FDCCheckManualApproval(
                application_id=data.application_id,
                status=data.status.strip().lower()
            ))

        row_id = row_id + 1

    return fdc_check_manual_approval_objects, logs


def validate_file_and_extension(upload_form):
    logs = ''
    if not upload_form.is_valid():
        for key in upload_form.errors:
            logs += upload_form.errors[key][0] + "\n"
        return logs

    file_path = upload_form.cleaned_data['file_field']
    extension = file_path.name.split('.')[-1]
    if extension != 'csv':
        logs = 'Please upload the correct file type: CSV'
        return logs

    return logs

@julo_login_required
@julo_login_required_multigroup(['product_manager'])
def fdc_stuck_application_upload_view(request):
    """
    Uploading CSV to add grab fdc stuck applications
    """
    template_name = 'object/fdc_stuck_application/fdc_stuck_application_upload.html'
    logs = ""
    upload_form = GrabFDCStuckApplicationUploadFileForm
    ok_couter = 0
    nok_couter = 0

    def _render():
        """lamda func to reduce code"""
        return render(
            request,
            template_name,
            {
                'form': upload_form,
                'logs': logs,
                'ok': ok_couter,
                'nok': nok_couter,
            },
        )

    if request.method == 'POST':
        upload_form = upload_form(request.POST, request.FILES)
        logs = validate_file_and_extension(upload_form)
        if logs:
            nok_couter += 1
            return _render()
        file_path = upload_form.cleaned_data['file_field']
        csv_file = []
        is_success_upload = False
        try:
            csv_file = pd.read_csv(file_path)
            fdc_check_manual_approval_objects, logs = validate_csv_file_and_get_app_ids_list(csv_file)
            if logs:
                nok_couter += 1
            if not logs:
                try:
                    with transaction.atomic():
                        FDCCheckManualApproval.objects.bulk_create(
                            fdc_check_manual_approval_objects, batch_size=30
                        )
                        logs += "FDC check stuck applications added successfully \n"
                        ok_couter += 1
                        is_success_upload = True
                    if is_success_upload:
                        for chunked_fdc_check_manual_approval_objects in chunks(fdc_check_manual_approval_objects, 10):
                            process_application_status_change.delay(chunked_fdc_check_manual_approval_objects)

                except IntegrityError as e:
                    logs += str(e)
                    nok_couter += 1

            return _render()
        except  KeyError:
            logs = "first row should contain label application_id and status"
            nok_couter += 1
        except  ValueError:
            logs = ("Something went wrong in csv file !!!  Please make sure all rows in csv file is filled with data "
                    "for application id and make sure application id should be integer")
            nok_couter += 1
        return _render()
    else:
        return _render()
