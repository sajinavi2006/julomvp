import logging

from datetime import datetime
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST, HTTP_201_CREATED, HTTP_403_FORBIDDEN
from django.db import transaction

from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.autodebet.models import AutodebetBenefit
from juloserver.autodebet.services.benefit_services import is_eligible_to_get_benefit, give_benefit
from juloserver.julo.models import MobileFeatureSetting
from juloserver.julo.utils import (
    display_rupiah,
    execute_after_transaction_safely,
)
from juloserver.payback.constants import (
    Messages,
    MobileFeatureNameConst,
)
from juloserver.payback.models import GopayAutodebetTransaction
from juloserver.payback.serializers import PaybackTransactionSerializer
from juloserver.payback.services.gopay import (
    GopayServices,
    is_eligible_change_url_gopay,
)
from juloserver.payback.services.payback import create_pbt_status_history
from juloserver.payback.status import PaybackTransStatus, PaymentServices
from juloserver.integapiv1.tasks import send_sms_async

from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment
from juloserver.refinancing.services import j1_refinancing_activation
from juloserver.moengage.tasks import update_moengage_for_payment_received_task
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
    response_template
)
from juloserver.autodebet.tasks import send_pn_gopay_autodebet_partial_repayment
logger = logging.getLogger(__name__)


def process_gopay_initial_for_account(request, amount, account, payment_method,
                                      is_gopay_tokenization=False):
    if request.user.customer != payment_method.customer:
        logger.error({
            'action': 'Init gopay transaction',
            'error': 'customer not match',
            'payment_method_customer_id': payment_method.customer.id,
            'requester_customer': request.user.customer.id
        })
        return Response(status=HTTP_400_BAD_REQUEST,
                        data={'error': 'User is not match with virtual account'})

    account_payment = account.get_oldest_unpaid_account_payment()
    if not account_payment:
        if is_gopay_tokenization:
            logger.error({
                'action': 'Init gopay tokenization transaction',
                'error': 'Account_payment not found'
            })
        else:
            logger.error({
                'action': 'Init gopay transaction',
                'error': 'Account_payment not found'
            })
        return Response(status=HTTP_400_BAD_REQUEST, data={'error': 'No active loan found'})
    # Initiate the transaction
    gopay_services = GopayServices()
    if is_gopay_tokenization:
        data, error = gopay_services.gopay_tokenization_init_account_payment_transaction(
            account_payment=account_payment,
            payment_method=payment_method,
            amount=amount)
        if error:
            if error == 'GoPay transaction is denied':
                return response_template(
                    status=HTTP_403_FORBIDDEN, success=False, message=[error])
            return general_error_response(error)
        if is_eligible_change_url_gopay(request.path):
            if 'web_linking' in data['gopay']:
                data['gopay']['web_linking'] = data['gopay']['web_linking'].replace(
                    'gopay.co.id/app', 'gojek.link/gopay'
                )
        return success_response(data)
    else:
        data = gopay_services.init_account_payment_transaction(
            account_payment=account_payment,
            payment_method=payment_method,
            amount=amount)

        serializer = PaybackTransactionSerializer(data['transaction'])
        res_data = serializer.data
        res_data['gopay'] = data['gopay']
        if is_eligible_change_url_gopay(request.path):
            if 'redirect_url' in res_data['gopay']:
                res_data['gopay']['redirect_url'] = ''
                mobile_feature_setting = MobileFeatureSetting.objects.filter(
                    feature_name=MobileFeatureNameConst.GOPAY_INIT_REDIRECT_URL,
                    is_active=True,
                ).last()
                if mobile_feature_setting and mobile_feature_setting.parameters.get('url'):
                    res_data['gopay']['redirect_url'] = \
                        mobile_feature_setting.parameters.get('url')
        return Response(status=HTTP_201_CREATED, data=res_data)


def process_gopay_repayment_for_account(payback_trx, data):
    note = 'payment with gopay'
    paid_date = datetime.strptime(data['transaction_time'], '%Y-%m-%d %H:%M:%S')
    old_status = payback_trx.status_code

    new_status = PaybackTransStatus.get_mapped_status(
        payment_service=PaymentServices.GOPAY, inbo_status=data['transaction_status'])
    with transaction.atomic():
        payback_trx.update_safely(
            status_code=new_status,
            status_desc=data['status_message'],
            transaction_date=paid_date)
        create_pbt_status_history(payback_trx, old_status, payback_trx.status_code)

        account_payment = payback_trx.account.get_oldest_unpaid_account_payment()
        j1_refinancing_activation(
            payback_trx, account_payment, payback_trx.transaction_date)
        process_j1_waiver_before_payment(account_payment, payback_trx.amount, paid_date)

        payment_processed = process_repayment_trx(payback_trx, note=note)

    if payment_processed:
        gopay_autodebet_transaction = GopayAutodebetTransaction.objects.filter(
            transaction_id=payback_trx.transaction_id
        ).last()
        if gopay_autodebet_transaction and gopay_autodebet_transaction.is_partial:
            send_pn_gopay_autodebet_partial_repayment.delay(
                gopay_autodebet_transaction.customer.id,
                gopay_autodebet_transaction.paid_amount
            )
        else:
            if gopay_autodebet_transaction:
                is_has_partial = GopayAutodebetTransaction.objects.filter(
                    subscription_id=gopay_autodebet_transaction.subscription_id,
                    is_partial=True
                ).exists()
                account = payback_trx.account
                benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)
                if benefit and not is_has_partial:
                    if gopay_autodebet_transaction.account_payment.dpd <= 0:
                        if is_eligible_to_get_benefit(account):
                            give_benefit(benefit, account, account_payment)
            execute_after_transaction_safely(
                lambda: update_moengage_for_payment_received_task.delay(payment_processed.id)
            )

    payment = account_payment.payment_set.filter(due_date=account_payment.due_date).first()
    if payment_processed and payment.payment_number == 1:
        send_sms_async.delay(
            application_id=payback_trx.account.application_set.last().id,
            template_code=Messages.PAYMENT_RECEIVED_TEMPLATE_CODE,
            context={'amount': display_rupiah(payback_trx.amount)}
        )

    return payment_processed
