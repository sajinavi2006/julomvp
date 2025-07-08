import csv
import io
import os
import logging
from fractions import Fraction
from math import ceil

from dateutil.relativedelta import relativedelta
from django.template.loader import render_to_string
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework_jwt.serializers import User

from juloserver.account.constants import AccountConstant
from juloserver.account.services.credit_limit import (
    get_proven_threshold,
    get_voice_recording,
    store_account_property_history,
)
from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.apiv2.services import get_latest_app_version
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import (
    Application,
    Customer,
    Partner,
    Workflow,
    ProductLine,
    PaybackTransaction,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import (
    update_customer_data,
    process_application_status_change,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tasks import create_application_checklist_async
from juloserver.julo.utils import (
    display_rupiah,
    format_e164_indo_phone_number,
    upload_file_to_oss,
    execute_after_transaction_safely
)
from juloserver.julovers.constants import (
    JuloverConst,
    JuloverPageConst,
    ProcessJuloversStatus,
)
from juloserver.julovers.exceptions import JuloverPageNotFound, JuloverException, JuloverNotFound
from juloserver.julovers.models import JuloverPage, Julovers
from juloserver.julovers.serializers import JuloversSerializer
from juloserver.julovers.utils import generate_nik, tokenize_julover_pii, detokenize_julover_pii
from juloserver.moengage.tasks import update_moengage_for_payment_received_task
from juloserver.account.models import (
    AccountProperty,
)

logger = logging.getLogger(__name__)


CSV_HEADER = [
    'fullname', 'email', 'address', 'birth_place', 'dob', 'mobile_phone_number', 'gender',
    'marital_status', 'job_industry', 'job_description', 'job_type', 'job_start',
    'bank_name', 'bank_account_number', 'name_in_bank', 'resign_date', 'set_limit', 'result upload'
]


def create_julovers_and_upload_result(upload_async_state):
    from juloserver.julovers.tasks import sync_julover_to_application
    upload_file = upload_async_state.file
    f = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(f, delimiter=',')
    input_emails = set()
    input_phones = set()
    for row in reader:
        input_emails.add(row['email'])
        input_phones.update(
            {row['mobile_phone_number'], format_e164_indo_phone_number(row['mobile_phone_number'])}
        )
    existed_emails = get_existed_emails(input_emails)
    existed_phones = get_existed_phones(input_phones)
    f.seek(0)
    reader = csv.DictReader(f, delimiter=',')

    is_success_all = True
    local_file_path = upload_async_state.file.path
    partner = Partner.objects.get(name=PartnerConstant.JULOVERS)
    with open(local_file_path, "w", encoding='utf-8-sig') as f:
        write = csv.writer(f)
        write.writerow(CSV_HEADER)
        for row in reader:
            if row['email'] in existed_emails:
                write.writerow(write_row_result(row, ProcessJuloversStatus.EMAIL_EXISTED))
                is_success_all = False
                continue
            if row['mobile_phone_number'] in existed_phones:
                write.writerow(write_row_result(row, ProcessJuloversStatus.PHONE_NUMBER_EXISTED))
                is_success_all = False
                continue
            serializer = JuloversSerializer(data=row)
            if serializer.is_valid():
                try:
                    julover = Julovers.objects.create(**serializer.validated_data)
                    sync_julover_to_application.delay(julover.id, partner.id)

                    write.writerow(write_row_result(row, ProcessJuloversStatus.SUCCESS))
                except IntegrityError as err_msg:
                    logger.error({
                        'action': 'create_julovers_and_upload_result',
                        'error': str(err_msg)
                    })
                    is_success_all = False
                    write.writerow(write_row_result(row, err_msg))
            else:
                is_success_all = False
                write.writerow(write_row_result(row, serializer.errors))
    upload_csv_data_to_oss(upload_async_state)
    return is_success_all


def write_row_result(row, result):
    return [
        row['fullname'], row['email'], row['address'], row['birth_place'], row['dob'],
        row['mobile_phone_number'], row['gender'], row['marital_status'],
        row['job_industry'], row['job_description'], row['job_type'],
        row['job_start'], row['bank_name'], row['bank_account_number'], row['name_in_bank'],
        row.get('resign_date'), row['set_limit'], result
    ]


def upload_csv_data_to_oss(upload_async_state):
    local_file_path = upload_async_state.file.path
    path_and_name, extension = os.path.splitext(local_file_path)
    file_name_elements = path_and_name.split('/')
    dest_name = "julovers/{}/{}".format(upload_async_state.id, file_name_elements[-1] + extension)
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_file_path, dest_name)

    if os.path.isfile(local_file_path):
        local_dir = os.path.dirname(local_file_path)
        upload_async_state.file.delete()
        os.rmdir(local_dir)

    upload_async_state.update_safely(url=dest_name)


def get_existed_emails(input_emails):
    return set(Application.objects.filter(
        email__in=input_emails
    ).values_list('email', flat=True))


def get_existed_phones(input_phones):
    return set(Application.objects.filter(
        mobile_phone_1__in=input_phones
    ).exclude(mobile_phone_1="").exclude(mobile_phone_1=None).values_list(
        'mobile_phone_1', flat=True)
    )


def process_julover_register(julover, partner_id):
    from juloserver.pin.services import CustomerPinService

    email = julover.email
    nik = generate_nik()

    julover_workflow = Workflow.objects.get(name=WorkflowConst.JULOVER)
    julover_product_line = ProductLine.objects.get(pk=ProductLineCodes.JULOVER)

    with transaction.atomic():
        user = User.objects.create(username=nik, email=email)

        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(user)

        user.set_password(user.pin)
        user.save()

        customer = Customer.objects.create(user=user, email=email, nik=nik)

        application = Application.objects.create(
            fullname=julover.fullname,
            customer=customer,
            ktp=nik,
            email=email,
            app_version=get_latest_app_version(),
            workflow=julover_workflow,
            product_line=julover_product_line,
            address_street_num=julover.address,
            dob=julover.dob,
            birth_place=julover.birth_place,
            mobile_phone_1=julover.mobile_phone_number,
            gender=julover.gender,
            marital_status=julover.marital_status,
            job_industry=julover.job_industry,
            job_type=julover.job_type,
            job_description=julover.job_description,
            job_start=julover.job_start,
            bank_name=julover.bank_name,
            bank_account_number=julover.bank_account_number,
            name_in_bank=julover.name_in_bank,
            loan_purpose='Kebutuhan sehari-hari',
            company_name='PT. Julo Teknologi Perdana',
            partner_id=partner_id,
        )
        update_customer_data(application)
        julover.update_safely(is_sync_application=True, application_id=application.id)

    process_application_status_change(
        application.id, ApplicationStatusCodes.FORM_PARTIAL,
        change_reason='system_triggered')

    create_application_checklist_async.delay(application.id)


    julover.update_safely(is_sync_application=True, customer_xid=customer.customer_xid)

    return application.id


def detokenize_and_log_julover_pii(julover_id):
    julover = Julovers.objects.filter(id=julover_id).first()
    if not julover:
        raise JuloverNotFound()
    detokenized_data = detokenize_julover_pii(julover.__dict__, julover.customer_xid)
    logger.info(detokenized_data)
    return detokenized_data


def tokenize_and_save_julover_pii(julover_id):
    julover = Julovers.objects.filter(id=julover_id).first()
    if not julover:
        raise JuloverNotFound()
    tokenized_data = tokenize_julover_pii(julover.__dict__, julover.customer_xid)
    if tokenized_data:
        julover.update_safely(**tokenized_data)


# -- julovers
def store_account_property_julover(application, set_limit):
    input_params = {
        'account': application.account,
        'pgood': AccountConstant.PGOOD_CUTOFF,
        'p0': AccountConstant.PGOOD_CUTOFF,
        'is_salaried': True,
        'is_proven': True,
        'is_premium_area': True,
        'proven_threshold': get_proven_threshold(set_limit),
        'voice_recording': get_voice_recording(is_proven=True),
        'concurrency': True,
        'is_entry_level': False,
    }

    account_property = AccountProperty.objects.create(**input_params)
    store_account_property_history(input_params, account_property)


def contruct_params_from_set_limit_for_julover(set_limit):
    limit_adjustment_factor = AccountConstant.\
        CREDIT_LIMIT_ADJUSTMENT_FACTOR_GTE_PGOOD_CUTOFF
    reduced_limit = set_limit
    simple_limit = Fraction(reduced_limit / limit_adjustment_factor)
    affordability_value = Fraction(
        (
            simple_limit *
            (1 + (JuloverConst.DEFAULT_MAX_DURATION * JuloverConst.DEFAULT_INTEREST))
        ),
        JuloverConst.DEFAULT_MAX_DURATION
    )
    return {
        'reduced_limit': reduced_limit,
        'simple_limit': ceil(simple_limit),
        'affordability_value': ceil(affordability_value),
        'limit_adjustment_factor': limit_adjustment_factor,
    }


def process_julovers_auto_repayment(
    account_payment, notes='Julover auto repayment'
):
    if account_payment.is_paid:
        raise JuloverException('Julover Account payment already paid', account_payment.id)

    now = timezone.localtime(timezone.now())
    today = now.date()
    amount = account_payment.due_amount
    transaction_id = 'julover-auto-{}{}'.format(today.strftime('%Y%m%d'), account_payment.id)
    with transaction.atomic():
        payback_transaction = PaybackTransaction.objects.create(
            is_processed=False,
            customer_id=account_payment.account.customer_id,
            account_id=account_payment.account_id,
            amount=amount,
            payback_service='Julover',
            status_desc=notes,
            transaction_id=transaction_id,
            transaction_date=now,
            payment_method=None,
        )
        payment_processed = process_repayment_trx(
            payback_transaction, note=notes, using_cashback=False
        )

    if payment_processed:
        execute_after_transaction_safely(
            lambda: update_moengage_for_payment_received_task.delay(payment_processed.id)
        )
        return True

    return False


class JuloverPageMapping:
    def email_content_at_190(application, reset_pin_key):
        page = JuloverPage.objects.filter(
            title=JuloverPageConst.EMAIL_AT_190,
            is_active=True,
        ).first()

        subject = page.extra_data['title']

        set_limit = Julovers.objects.filter(
            email__iexact=application.email,
        ).values_list('set_limit', flat=True).last()

        reset_link_host = settings.RESET_PIN_JULO_ONE_LINK_HOST
        reset_pin_page_link = reset_link_host + reset_pin_key + '/' + '?julover=true'

        format = {
            'first_name': application.first_name_only,
            'set_limit': display_rupiah(set_limit),
            'reset_link': reset_pin_page_link,
            'email': application.email,
            'mobile_phone_number': application.mobile_phone_1,
            'dob': application.dob,
            'bank_account_number': application.bank_account_number,
            'job_description': application.job_description,
            'full_name': application.full_name_only,
            'bank_name': application.bank_name,
            'name_in_bank': application.name_in_bank,
        }
        page.content = page.content.format(**format)
        content = render_to_string(
            template_name='julovers/email_reset_pin.html',
            context={'page': page},
        )
        return subject, content

    MAP = {
        JuloverPageConst.EMAIL_AT_190: email_content_at_190,
    }

    @classmethod
    def get_julover_page_content(cls, title, application, *args, **kwargs):
        func = cls.MAP.get(title, None)
        if func is None:
            raise JuloverPageNotFound

        return func(application, *args, **kwargs)


def get_first_payment_date():
    """
    Jira Card: https://juloprojects.atlassian.net/browse/CLS3-402
    When my calculated days before pay day is >= 15 (payday- cdate),
        my first due_date should be on the current month
    When my calculated days before pay day is < 15 (payday- cdate),
        my first due_date should be on the next month
    """
    today_date = timezone.localtime(timezone.now()).date()
    first_payment_date = today_date + relativedelta(day=JuloverConst.DEFAULT_CYCLE_PAYDAY)

    if (first_payment_date - today_date).days >= 15:
        return first_payment_date

    return first_payment_date + relativedelta(months=1)


def fetch_julovers_to_be_synced_for_pii_vault(limit=1000):
    query = Q(fullname_tokenized__startswith="JULO:")
    query.add(Q(fullname_tokenized__isnull=True,fullname__isnull=False), Q.OR)
    query.add(Q(mobile_phone_number_tokenized__startswith="JULO:"), Q.OR)
    query.add(Q(mobile_phone_number_tokenized__isnull=True,mobile_phone_number__isnull=False), Q.OR)
    query.add(Q(email_tokenized__startswith="JULO:"), Q.OR)
    query.add(Q(email_tokenized__isnull=True,email__isnull=False), Q.OR)
    query.add(Q(real_nik_tokenized__startswith="JULO:"), Q.OR)
    query.add(Q(real_nik_tokenized__isnull=True,real_nik__isnull=False), Q.OR)
    julovers = Julovers.objects.filter(query).filter(customer_xid__isnull=False).only('id')[:limit]

    return julovers
