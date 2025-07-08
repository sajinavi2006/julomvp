from builtins import str
import logging

from django.db import transaction
from django.db.models import Sum, F

from juloserver.account.constants import (
    AccountConstant,
    FeatureNameConst,
)
from juloserver.julo.models import (
    Loan,
    FeatureSetting,
)
from juloserver.loan_selloff.models import (
    LoanSelloff,
    LoanSelloffBatch,
)
from juloserver.loan_selloff.constants import SelloffBatchConst
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.models import (
    CustomerAppAction,
    EmailHistory,
)
from juloserver.julo.clients import get_julo_email_client

from django.utils import timezone
from babel.dates import format_date

from juloserver.minisquad.models import CollectionBucketInhouseVendor
from juloserver.collection_vendor.models import CollectionVendorAssignment

logger = logging.getLogger(__name__)

def calculate_remaining_principal(loan):
    total_remaining_principal = loan.payment_set.not_paid_active().aggregate(
        total_principal=Sum(F('installment_principal')-F('paid_principal'))
    )['total_principal']
    return  total_remaining_principal or 0

def calculate_remaining_interest(loan):
    total_remaining_interest = loan.payment_set.not_paid_active().aggregate(
        total_interest=Sum(F('installment_interest')-F('paid_interest'))
    )['total_interest']
    return  total_remaining_interest or 0

def calculate_remaining_late_fee(loan):
    total_remaining_late_fee = loan.payment_set.not_paid_active().aggregate(
        total_late_fee=Sum(F('late_fee_amount')-F('paid_late_fee'))
    )['total_late_fee']
    return  total_remaining_late_fee or 0

def calculate_selloff_proceeds_value(loan_selloff_batch,total_principal,total_interest, total_late_fee):
    parameter = loan_selloff_batch.parameter
    pct_of_parameter = loan_selloff_batch.pct_of_parameter

    if parameter == SelloffBatchConst.PRINCIPAL:
        return total_principal*pct_of_parameter
    if parameter == SelloffBatchConst.PRINCIPAL_AND_INTEREST:
        return (total_principal+total_interest)*pct_of_parameter
    if parameter == SelloffBatchConst.TOTAL_OUTSTANDING:
        return (total_principal + total_interest + total_late_fee) * pct_of_parameter
    return 0


def process_loan_selloff_by_loan_id(loan_selloff_batch, loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return False, 'Loan not found'
    total_remaining_principal = calculate_remaining_principal(loan)
    total_remaining_interest = calculate_remaining_interest(loan)
    total_remaining_late_fee = calculate_remaining_late_fee(loan)
    exist_loan_selloff = LoanSelloff.objects.get_or_none(loan=loan)
    if exist_loan_selloff:
        return False, 'skipped, Loan with id: %s already sold off with loan_selloff_id: %s'\
               % (str(loan.id),str(exist_loan_selloff.id))
    try:
        with transaction.atomic():
            LoanSelloff.objects.create(
                loan_selloff_batch=loan_selloff_batch,
                loan=loan,
                principal_at_selloff=total_remaining_principal,
                interest_at_selloff=total_remaining_interest,
                late_fee_at_selloff=total_remaining_late_fee,
                loan_selloff_proceeds_value=calculate_selloff_proceeds_value(
                    loan_selloff_batch,
                    total_remaining_principal,
                    total_remaining_interest,
                    total_remaining_late_fee
                )
            )
            loan.change_status(LoanStatusCodes.SELL_OFF)
            loan.save()
            customer = loan.customer
            CustomerAppAction.objects.bulk_create(
                [
                    CustomerAppAction(customer=customer, action='force_upgrade'),
                    CustomerAppAction(customer=customer, action='sell_off')
                ]
            )
            julo_email_client = get_julo_email_client()

            selloff_data = {'total_outstanding': (total_remaining_principal+
                                                  total_remaining_interest+
                                                  total_remaining_late_fee),
                            'ajb_number': '05/JTP/II/LEG/2020',
                            'ajb_date': '6-Feb-2020',
                            'buyer_vendor_name': 'PT R2P Invest PTE LTD',
                            'collector_vendor_name': 'PT Jasa Konsultasi MBA',
                            'collector_vendor_phone' : '+628111436616'
                            }
            status, headers, subject, msg, template = julo_email_client.email_notify_loan_selloff(loan, selloff_data)

            EmailHistory.objects.create(
                customer=customer,
                sg_message_id=headers["X-Message-Id"],
                to_email=customer.email,
                subject=subject,
                application=loan.application,
                message_content=msg,
                template_code=template,
            )

            logger.info({
                "action": "email_december_hi_season",
                "customer_id":customer.id,
                "promo_type": template
            })

            return True, 'Loan sell off for loan_id: %s succeeded' % str(loan.id)

    except Exception as e:
        return False, str(e)


def process_account_selloff_j1(account, loan_selloff_batch_id, is_send_email=True):
    from juloserver.account.services.account_related import process_change_account_status
    if not account:
        return False, 'Account not found'

    customer = account.customer
    try:
        with transaction.atomic():
            # if you insert into customerAppAction with action sell_off customer will get
            # force upgrade if app_version below the
            CustomerAppAction.objects.create(customer=customer, action='sell_off')
            # force update status even 332 ( terminated ) that's why we need to put
            # manual_change=True
            process_change_account_status(
                account,
                AccountConstant.STATUS_CODE.sold_off,
                'move to sell off',
                manual_change=True,
            )
            if is_send_email:
                trigger_send_email_selloff(account, loan_selloff_batch_id=loan_selloff_batch_id)
            # trigger unassign vendor if exists
            filter_vendor = {'account_payment__account_id': account.id}
            CollectionBucketInhouseVendor.objects.filter(**filter_vendor).delete()
            CollectionVendorAssignment.objects.filter(**filter_vendor).update(is_active_assignment=False)

            return True, 'Loan sell off for account: %s succeeded' % str(account.id)

    except Exception as e:
        return False, str(e)


def trigger_send_email_selloff(account, loan_selloff_batch_id):
    customer = account.customer
    try:
        julo_email_client = get_julo_email_client()
        loan_selloff_batch = LoanSelloffBatch.objects.get(pk=loan_selloff_batch_id)
        application = account.last_application
        context = get_selloff_email_context(account, loan_selloff_batch)

        _, headers, subject, msg, _ = julo_email_client.email_notify_loan_selloff_j1(context, customer.email)
        template = "asset_selloff_{}.html".format(loan_selloff_batch_id)

        EmailHistory.objects.create(
            customer=customer,
            sg_message_id=headers["X-Message-Id"],
            to_email=customer.email,
            subject=subject,
            application=application,
            message_content=msg,
            template_code=template,
        )

        logger.info({
            "action": "trigger_send_email_selloff",
            "customer_id": customer.id,
            "template": template
        })

    except Exception as e:
        logger.error(
            {
                'action': 'trigger_send_email_selloff',
                'data': {'customer_id': customer.id},
                'response': "failed to send email",
                'error': e
            }
        )

    
def get_selloff_email_context(account, loan_selloff_batch):
    customer = account.customer
    application = account.last_application
    oldest_account_payment = account.get_oldest_unpaid_account_payment()
    account_payments = account.accountpayment_set.all().not_paid_active().order_by('due_date')
    account_payments_list = list(account_payments)
    skrtp_list = []
    skrtp_loans = account.loan_set.all().all_active_julo_one().distinct('pk')

    for skrtp_loan in skrtp_loans:
        if not skrtp_loan.sphp_accepted_ts:
            continue
        skrtp_list.append(
            dict(
                skrtp_no=skrtp_loan.loan_xid,
                skrtp_sign_date=format_date(
                    timezone.localtime(skrtp_loan.sphp_accepted_ts).date(),
                    'dd MMMM yyyy',
                    locale='id_ID',
                ),
            )
        )
    vendor_contact_number, vendor_email, vendor_contact_info = '-', '-', ''
    j1_selloff_config = FeatureSetting.objects.get_or_none(
        is_active=True, feature_name=FeatureNameConst.ACCOUNT_SELLOFF_CONFIG
    )
    if j1_selloff_config:
        selloff_param = j1_selloff_config.parameters
        vendor_contact_number = selloff_param.get('vendor_phone_number', '-')
        vendor_email = selloff_param.get('vendor_email', '-')
        vendor_contact_info = selloff_param.get('vendor_contact_info', '')

    context = {
        'fullname': customer.fullname,
        'address': application.full_address,
        'skrtp_list':skrtp_list,
        'account_payments_list': account_payments_list,
        'oldest_due_date': format_date(
            oldest_account_payment.due_date,'dd MMMM yyyy', locale='id_ID'),
        'vendor_name': loan_selloff_batch.vendor,
        'vendor_contact_number': vendor_contact_number,
        'vendor_email': vendor_email,
        'vendor_contact_info': vendor_contact_info,
        'total_outstanding': account.get_total_outstanding_amount()
    }
    return context
