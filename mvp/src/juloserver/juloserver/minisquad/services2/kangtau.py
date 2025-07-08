from django.db import transaction
from datetime import datetime
from django.utils.timezone import make_aware
from juloserver.minisquad.models import (
    KangtauUploadedCustomerList,
)
import logging
from juloserver.minisquad.clients import get_julo_kangtau_client
from django.db.models import Sum
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.minisquad.constants import KangtauBucketWhitelist


logger = logging.getLogger(__name__)

class KangtauService(object):
    UPDATE_FIELDS = [
        "customer_name",
        "loan_amount",
        "leader_name",
        "leader_unique_id",
        "agent_name",
        "agent_unique_id",
        "remark_created_by",
        "remark_created_at",
        "status",
        "remark",
        "contacted_person",
        "notes",
        "payment_proof_preview_urls",
    ]

    def parse_datetime(dt_str: str) -> datetime:
        # Example format: "Apr 23, 2025, 8:22 AM"
        naive = datetime.strptime(dt_str, "%b %d, %Y, %I:%M %p")
        return make_aware(naive)

    def get_customer_form_list(page=1, search_key="", take=15):
        client = get_julo_kangtau_client()

        customer_forms = client.get_customer_form_list(
            page=page,
            search_key=search_key,
            take=take,
        )

        return customer_forms

    def get_customer_statistic(self):
        client = get_julo_kangtau_client()

        customer_statistic = client.get_customer_statistic()

        return customer_statistic

    def create_customer_form(self, bucket_name):
        client = get_julo_kangtau_client()
        form_name = KangtauService.create_customer_form_name(bucket_name)
        attributes = [
            {
                "name": "DPD",
                "type": "NUMBER",
                "isCallable": False,
                "isWhatsappable": False,
                "isEditable": True,
                "isRequired": True,
                "showOnList": True,
                "showOnAgentView": True,
                "isMasked": False,
            }
        ]

        customer_form = client.create_customer_form(
            form_name,
            attributes,
        )

        return customer_form

    def create_customer_form_name(bucket_name):
        return f"Automatic_{bucket_name}_KangTau_{datetime.now().strftime('%d_%B_%Y')}"

    def upload_customer_list(client, form_id, payload, task_id, bucket_name, api_batch=1000):
        """
        Uploads payload to Kangtau API in batches, with retry logic.

        Args:
            client: The Julo Kangtau API client.
            form_id: ID of the customer form.
            payload: List of serialized record dicts.
            task_id: Celery task ID for logging.
            bucket_name: Current bucket name for logging.
            api_batch: Size of each API batch.
        """
        for i in range(0, len(payload), api_batch):
            batch = payload[i : i + api_batch]
            try:
                client.upsert_bulk_customer_data(
                    customerFormId=form_id,
                    fields=['DPD'],
                    data=batch,
                )
                logger.info(
                    'Task %s: uploaded API batch %d for %s',
                    task_id,
                    i // api_batch + 1,
                    bucket_name,
                )
            except Exception as exc:
                logger.error(
                    'Task %s failed API batch %d for %s: %s',
                    task_id,
                    i // api_batch + 1,
                    bucket_name,
                    exc,
                )
                raise

    def serialize_customer_list_record(record):
        outstanding = KangtauService.calculate_outstanding(record)
        due_date = record.account_payment.due_date.strftime('%Y-%m-%d')
        return {
            'loanId': record.account_id,
            'name': record.nama_customer or '',
            'phoneNumber': record.phonenumber,
            'loanAmount': record.total_due_amount,
            'outstandingAmount': outstanding,
            'dueDate': due_date,
            'DPD': str(record.dpd),
        }

    def serialize_customer_list_record_t0(record):
        outstanding = KangtauService.calculate_outstanding(record)
        due_date = record.due_date.strftime('%Y-%m-%d')
        return {
            'loanId': record.account_id,
            'name': record.account.customer.fullname or '',
            'phoneNumber': record.account.customer.phone,
            'loanAmount': record.due_amount,
            'outstandingAmount': outstanding,
            'dueDate': due_date,
            'DPD': str(record.dpd),
        }

    def calculate_outstanding(record):
        return (
            record.account.accountpayment_set.normal()
            .filter(status_id__lte=PaymentStatusCodes.PAID_ON_TIME)
            .aggregate(Sum('due_amount'))['due_amount__sum']
            or 0
        )

    def build_uploaded_object(record, form_id, form_name, bucket_name):
        """
        Returns a KangtauUploadedCustomerList instance based on bucket logic.
        """
        outstanding = KangtauService.calculate_outstanding(record)
        if bucket_name == 'B0':
            return KangtauUploadedCustomerList(
                loan_id=record.account_id,
                name=record.account.customer.fullname or '',
                phone_number=record.account.customer.phone,
                loan_amount=record.due_amount,
                outstanding_amount=outstanding,
                due_date=record.due_date,
                bucket=KangtauBucketWhitelist.JULO_T0,
                dpd=record.dpd,
                customer_form_id=form_id,
                customer_form_name=form_name,
            )
        else:
            return KangtauUploadedCustomerList(
                loan_id=record.account_id,
                name=record.nama_customer or '',
                phone_number=record.phonenumber,
                loan_amount=record.total_due_amount,
                outstanding_amount=outstanding,
                due_date=record.account_payment.due_date,
                bucket=record.bucket_name,
                dpd=record.dpd,
                customer_form_id=form_id,
                customer_form_name=form_name,
            )
