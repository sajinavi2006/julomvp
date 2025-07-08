"""
ayoconnect.py
serve ayoconnect api
"""
from builtins import str
from builtins import object
from http import HTTPStatus
import logging
import requests

from django.utils import timezone
from django.db import transaction
from rest_framework import status as http_status_codes

from juloserver.disbursement.models import Disbursement
from juloserver.grab.models import (
    PaymentGatewayVendor,
    PaymentGatewayCustomerData,
    PaymentGatewayCustomerDataHistory,
    PaymentGatewayBankCode,
    PaymentGatewayTransaction
)
from juloserver.disbursement.clients import get_ayoconnect_client
from juloserver.disbursement.constants import (
    AyoconnectBeneficiaryStatus, DisbursementStatus, AyoconnectConst, NameBankValidationStatus,
    AyoconnectErrorCodes, AyoconnectErrorReason)
from juloserver.disbursement.exceptions import (
    AyoconnectApiError,
    AyoconnectServiceError,
    AyoconnectServiceForceSwitchToXfersError,
)
from juloserver.julo.models import Loan
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.disbursement.utils import generate_unique_id

logger = logging.getLogger(__name__)


class AyoconnectService(object):
    def __init__(self) -> None:
        self.client = get_ayoconnect_client()
        self.sentry_client = get_julo_sentry_client()

    def get_payment_gateway(self):
        return PaymentGatewayVendor.objects.get_or_none(name="ayoconnect")

    def get_payment_gateway_bank(self, bank_id):
        payment_gateway_vendor = self.get_payment_gateway()
        return PaymentGatewayBankCode.objects.filter(
            bank_id=bank_id,
            is_active=True,
            payment_gateway_vendor=payment_gateway_vendor
        ).last()

    def create_beneficiary(self, payment_gateway_vendor, customer_id, phone_number, beneficiary_id,
                           account_number, swift_bank_code, account_type, external_customer_id,
                           status):
        payment_gateway_customer_data = PaymentGatewayCustomerData.objects.create(
            payment_gateway_vendor=payment_gateway_vendor,
            customer_id=customer_id,
            phone_number=phone_number,
            beneficiary_id=beneficiary_id,
            account_number=account_number,
            bank_code=swift_bank_code,
            account_type=account_type,
            status=status,
            external_customer_id=external_customer_id
        )
        return payment_gateway_customer_data

    def update_beneficiary(self, customer_id, beneficiary_id, account_number, swift_bank_code,
                           old_phone_number, new_phone_number, external_customer_id, account_type,
                           status, is_j1=False):
        if is_j1:
            existing_pg_customer_data = PaymentGatewayCustomerData.objects.filter(
                customer_id=customer_id,
                phone_number=new_phone_number,
                account_number=account_number,
                bank_code=swift_bank_code
            ).last()
        else:
            existing_pg_customer_data = PaymentGatewayCustomerData.objects.filter(
                customer_id=customer_id).last()

        payment_gateway_customer_data_history = PaymentGatewayCustomerDataHistory.objects.create(
            payment_gateway_customer_data=existing_pg_customer_data,
            old_beneficiary_id=existing_pg_customer_data.beneficiary_id,
            new_beneficiary_id=beneficiary_id,
            old_account_number=existing_pg_customer_data.account_number,
            new_account_number=account_number,
            old_bank_code=existing_pg_customer_data.bank_code,
            new_bank_code=swift_bank_code,
            old_status=existing_pg_customer_data.status,
            new_status=status,
            old_phone_number=old_phone_number,
            new_phone_number=new_phone_number,
            old_external_customer_id=existing_pg_customer_data.external_customer_id,
            new_external_customer_id=external_customer_id
        )

        existing_pg_customer_data.beneficiary_id = beneficiary_id
        existing_pg_customer_data.account_number = account_number
        existing_pg_customer_data.bank_code = swift_bank_code
        existing_pg_customer_data.account_type = account_type
        existing_pg_customer_data.status = status
        existing_pg_customer_data.external_customer_id = external_customer_id
        existing_pg_customer_data.save()

        return existing_pg_customer_data, payment_gateway_customer_data_history

    def update_beneficiary_j1(
        self, beneficiary_id, account_type, status
    ):
        pg_customer_datas = PaymentGatewayCustomerData.objects.filter(
            beneficiary_id=beneficiary_id,
        )
        payment_gateway_customer_data_histories = []
        for pg_customer_data in pg_customer_datas:
            if status != pg_customer_data.status:
                payment_gateway_customer_data_histories.append(
                    PaymentGatewayCustomerDataHistory(
                        payment_gateway_customer_data=pg_customer_data,
                        old_beneficiary_id=pg_customer_data.beneficiary_id,
                        new_beneficiary_id=beneficiary_id,
                        old_account_number=pg_customer_data.account_number,
                        new_account_number=pg_customer_data.account_number,
                        old_bank_code=pg_customer_data.bank_code,
                        new_bank_code=pg_customer_data.bank_code,
                        old_status=pg_customer_data.status,
                        new_status=status,
                        old_phone_number=pg_customer_data.phone_number,
                        new_phone_number=pg_customer_data.phone_number,
                        old_external_customer_id=pg_customer_data.external_customer_id,
                        new_external_customer_id=pg_customer_data.external_customer_id
                    )
                )

        if payment_gateway_customer_data_histories:
            PaymentGatewayCustomerDataHistory.objects.bulk_create(
                payment_gateway_customer_data_histories
            )
            pg_customer_datas.update(
                status=status,
                account_type=account_type,
            )

        return pg_customer_datas, payment_gateway_customer_data_histories

    def create_or_update_beneficiary(
            self, customer_id: int, application_id: int, account_number: str, swift_bank_code: str,
            new_phone_number: str, old_phone_number: str = None, is_without_retry: bool = False,
            is_j1: bool = False):
        registered = False
        updated = False
        payment_gateway_vendor = self.get_payment_gateway()
        log_data = {
            "payment_gateway_vendor_id": payment_gateway_vendor.id,
            "customer_id": customer_id,
            "application_id": application_id
        }

        try:
            token_response = self.client.get_token(log_data=log_data)
            user_token = token_response.get("accessToken")
        except AyoconnectApiError as err:
            logger.error({
                'function': 'AyoconnectService -> create_or_update_beneficiary()',
                'error': err.message
            })
            raise AyoconnectServiceError(err.message)

        try:
            response_register = self.client.add_beneficiary(user_token, account_number,
                                                            swift_bank_code, new_phone_number,
                                                            log_data=log_data,
                                                            is_without_retry=is_without_retry)
        except AyoconnectApiError as err:
            logger.error({
                'function': 'AyoconnectService -> create_or_update_beneficiary()',
                'error': err.message
            })
            if err.error_code in AyoconnectErrorCodes.force_switch_to_xfers_error_codes():
                raise AyoconnectServiceForceSwitchToXfersError(
                    message=err.message, error_code=err.error_code
                )
            raise AyoconnectServiceError(err.message)
        if response_register.get("code") and response_register.get("code") == HTTPStatus.ACCEPTED:
            beneficiary_details = response_register.get("beneficiaryDetails")
            beneficiary_id = beneficiary_details.get("beneficiaryId")
            account_type = beneficiary_details.get("accountType")
            external_customer_id = response_register.get("customerId")
            if is_j1:
                # for J1, one customer can have multiple beneficiary id
                # because one customer can disburse to multiple account number
                # Only create new record when users change their phone number OR bank account
                # => to easier trace which customer data was used to disburse
                existing_pg_customer_data = PaymentGatewayCustomerData.objects.filter(
                    customer_id=customer_id,
                    phone_number=new_phone_number,
                    account_number=account_number,
                    bank_code=swift_bank_code
                ).exists()
            else:
                # for Grab, create new customer data if customer_id doesn't exist yet
                existing_pg_customer_data = PaymentGatewayCustomerData.objects.filter(
                    customer_id=customer_id
                ).exists()
            if existing_pg_customer_data:
                with transaction.atomic():
                    self.update_beneficiary(customer_id,
                                            beneficiary_id,
                                            account_number,
                                            swift_bank_code,
                                            old_phone_number,
                                            new_phone_number,
                                            external_customer_id,
                                            account_type,
                                            AyoconnectBeneficiaryStatus.INACTIVE,
                                            is_j1=is_j1)

                    updated = True
            else:
                self.create_beneficiary(payment_gateway_vendor,
                                        customer_id,
                                        new_phone_number,
                                        beneficiary_id,
                                        account_number,
                                        swift_bank_code,
                                        account_type,
                                        external_customer_id,
                                        AyoconnectBeneficiaryStatus.INACTIVE)
                registered = True

        return registered, updated

    def validate(self, name_bank_validation):
        logger.info({
            'function': 'AyoconnectService -> validate()',
            'action': 'start_validating_ayoconnect',
            'name_bank_validation_data': {
                'account_number': name_bank_validation.account_number,
                'bank_code': name_bank_validation.bank_code,
                'mobile_number': name_bank_validation.mobile_phone,
                'name_in_bank': name_bank_validation.name_in_bank,
            }
        })

        account_number = name_bank_validation.account_number
        bank_code = name_bank_validation.bank_code

        response_validate = {}
        try:
            token_response = self.client.get_user_token(name_bank_validation.mobile_phone)
            logger.info({
                'function': 'AyoconnectService -> validate()',
                'token_response': token_response,
                'name_bank_validation': name_bank_validation.id
            })
            user_token = token_response['user_api_token'] if token_response else None

            response = self.client.add_beneficiary(user_token,
                                                   account_number,
                                                   bank_code,
                                                   name_bank_validation.mobile_phone)
            bank_id = response[0]['id']
            validated_name = response[0]['detected_name']
            response_validate['id'] = bank_id
            response_validate['status'] = NameBankValidationStatus.SUCCESS
            response_validate['validated_name'] = validated_name
            response_validate['reason'] = 'success'
            response_validate['error_message'] = None
            response_validate['account_no'] = response[0]['account_no']
            response_validate['bank_abbrev'] = response[0]['bank_abbrev']

            logger.info({
                'function': 'AyoconnectService -> validate()',
                'response': response,
                'name_bank_validation': name_bank_validation.id
            })

        except AyoconnectApiError as e:

            logger.error({
                'function': 'AyoconnectService -> validate()',
                'error': str(e),
                'name_bank_validation': name_bank_validation.id
            })

            response_validate['id'] = None
            response_validate['status'] = NameBankValidationStatus.NAME_INVALID
            response_validate['validated_name'] = None
            response_validate['reason'] = "Failed to add beneficiary"
            response_validate['error_message'] = str(e)
            response_validate['account_no'] = None
            response_validate['bank_abbrev'] = None

        return response_validate

    def get_balance(self, user_token):
        ayoconnect_balance = 0
        try:
            response = self.client.get_merchant_balance(user_token, n_retry=3)
        except AyoconnectApiError as e:
            logger.error({
                'function': 'AyoconnectService -> get_balance()',
                'error': str(e),
                'ayoconnect_balance': ayoconnect_balance
            })
            return str(e), False
        account_info = response.get("accountInfo")
        if account_info and account_info[0]:
            ayoconnect_balance = account_info[0].get("availableBalance").get("value", 0)
        return ayoconnect_balance

    def check_balance(self, amount):
        token_response = self.client.get_token()
        user_token = token_response.get("accessToken")
        ayoconnect_balance = self.get_balance(user_token)
        try:
            if float(ayoconnect_balance) > amount:
                return DisbursementStatus.SUFFICIENT_BALANCE, True, ayoconnect_balance
            return DisbursementStatus.INSUFICIENT_BALANCE, False, ayoconnect_balance
        except Exception as e:
            logger.error({
                'function': 'AyoconnectService -> check_balance()',
                'error': str(e),
                'ayoconnect_balance': ayoconnect_balance
            })
            return str(e), False, ayoconnect_balance

    def create_disbursement(self, data):
        # convert to required format amount for ayoconnect
        amount = data.get('amount')
        user_token = data.get('user_token')
        pg_cust_data = data.get('pg_cust_data')
        remark = data.get('remark')
        log_data = data.get('log_data')
        n_retry = data.get('n_retry', 1)
        # will raise error if unique id is not there, it's expected.
        unique_id = data['unique_id']

        response_disburse = {}
        ayoconnect_amount = "{}.00".format(str(amount))
        try:
            response = self.client.create_disbursement(
                user_token=user_token,
                ayoconnect_customer_id=pg_cust_data.external_customer_id,
                beneficiary_id=pg_cust_data.beneficiary_id,
                amount=ayoconnect_amount,
                unique_id=unique_id,
                remark=remark,
                log_data=log_data,
                n_retry=n_retry,
            )
            transaction_data = response.get('transaction')
            response_disburse['response_time'] = timezone.localtime(timezone.now())
            response_disburse['status'] = AyoconnectConst.DISBURSEMENT_MAP_STATUS[
                transaction_data.get("status")]
            response_disburse['id'] = response.get("transactionId")
            response_disburse['amount'] = transaction_data.get("amount")
            response_disburse['reason'] = "disbursement created"
            response_disburse['refference_id'] = transaction_data.get('referenceNumber')
        # i know this is not best practice
        # but we just sent this exception to sentry
        # and then mark the disbursement stuck at pending
        except AyoconnectApiError as error:
            self.sentry_client.capture_exceptions()
            response_disburse['response_time'] = timezone.localtime(timezone.now())
            response_disburse['id'] = unique_id
            response_disburse['status'] = DisbursementStatus.PENDING
            response_disburse['amount'] = amount
            response_disburse['reason'] = str(error)
            response_disburse['error_code'] = error.error_code

            err_code = error.error_code
            if err_code and err_code == AyoconnectErrorCodes.SYSTEM_UNDER_MAINTENANCE:
                response_disburse['reason'] = AyoconnectErrorReason.SYSTEM_UNDER_MAINTENANCE

        return response_disburse

    def save_unique_id(self, unique_id, disbursement, payment_gateway_vendor):
        PaymentGatewayTransaction.objects.create(
            disbursement_id=disbursement.id,
            correlation_id=unique_id,
            transaction_id=unique_id,
            payment_gateway_vendor=payment_gateway_vendor
        )

    def disburse(self, disbursement, beneficiary_id=None, n_retry=1):
        from juloserver.disbursement.services import get_name_bank_validation
        response_disburse = {}
        amount = disbursement.amount

        loan = Loan.objects.get_or_none(loan_xid=disbursement.external_id)
        if not loan:
            response_disburse['response_time'] = None
            response_disburse['status'] = DisbursementStatus.PENDING
            response_disburse['id'] = None
            response_disburse['amount'] = amount
            response_disburse['reason'] = "loan doesnt exist for loan_xid {}".format(
                disbursement.external_id)
            return response_disburse

        application = loan.application
        if not application:
            application = loan.get_application
        payment_gateway_vendor = self.get_payment_gateway()

        if beneficiary_id:
            # case for j1
            pg_cust_data = PaymentGatewayCustomerData.objects.filter(
                customer_id=loan.customer_id,
                beneficiary_id=beneficiary_id
            ).last()
        else:
            # case for grab
            name_bank_validation = get_name_bank_validation(loan.name_bank_validation_id)
            account_number = name_bank_validation['account_number']
            pg_cust_data = PaymentGatewayCustomerData.objects.filter(
                customer_id=loan.customer_id,
                payment_gateway_vendor=payment_gateway_vendor,
                account_number=account_number,
            ).last()

        log_data = {
            "payment_gateway_vendor_id": payment_gateway_vendor.id,
            "customer_id": loan.customer_id,
            "application_id": application.id
        }

        try:
            token_response = self.client.get_token(log_data=log_data)
            user_token = token_response.get("accessToken")
        except AyoconnectApiError as err:
            logger.error({
                'function': 'AyoconnectService -> disburse()',
                'error': str(err)
            })
            response_disburse['response_time'] = None
            response_disburse['status'] = DisbursementStatus.FAILED
            response_disburse['id'] = None
            response_disburse['amount'] = amount
            response_disburse['reason'] = "error unexpected get token response"
            response_disburse['error_code'] = AyoconnectErrorCodes.FAILED_ACCESS_TOKEN
            return response_disburse

        if not user_token:
            response_disburse['response_time'] = None
            response_disburse['status'] = DisbursementStatus.FAILED
            response_disburse['id'] = None
            response_disburse['amount'] = amount
            response_disburse['reason'] = "unauthorized or token expired"
            response_disburse['error_code'] = AyoconnectErrorCodes.FAILED_ACCESS_TOKEN
            return response_disburse

        remark = "Disbursement {}{}".format(
            disbursement.external_id,
            application.product_line_code
        )

        unique_id = self.get_unique_id(disbursement_id=disbursement.id)
        disbursement.update_safely(disburse_id=unique_id)

        self.save_unique_id(
            unique_id=unique_id,
            disbursement=disbursement,
            payment_gateway_vendor=payment_gateway_vendor
        )

        response_disburse = self.create_disbursement({
            'amount': amount,
            'user_token': user_token,
            'pg_cust_data': pg_cust_data,
            'remark': remark,
            'log_data': log_data,
            'n_retry': n_retry,
            'unique_id': unique_id})
        return response_disburse

    def get_disbursement_status(self, data):
        user_token = data.get('user_token')
        ayoconnect_customer_id = data.get('ayoconnect_customer_id')
        beneficiary_id = data.get('beneficiary_id')
        a_correlation_id = data.get('a_correlation_id')
        reference_id = data.get('reference_id')
        log_data = data.get('log_data')
        n_retry = data.get('n_retry', 1)

        is_retrying = False
        response = None
        try:
            response = self.client.get_disbursement_status(
                user_token=user_token,
                ayoconnect_customer_id=ayoconnect_customer_id,
                beneficiary_id=beneficiary_id,
                a_correlation_id=a_correlation_id,
                reference_id=reference_id,
                log_data=log_data,
                n_retry=n_retry
            )
            logger.info({
                'function': 'AyoconnectService -> check_disburse_status()',
                'response': response
            })
            if response.get("transaction").get('status') in {
                AyoconnectConst.DISBURSEMENT_STATUS_FAILED,
                AyoconnectConst.DISBURSEMENT_STATUS_CANCELLED,
                AyoconnectConst.DISBURSEMENT_STATUS_REFUNDED
            }:
                is_retrying = True
        except (TimeoutError, requests.exceptions.Timeout) as error:
            logger.error({
                'function': 'AyoconnectService -> check_disburse_status()',
                'error': str(error)
            })
            is_retrying = False
        # dear future programmer, this is Exception actually
        # just record to sentry for now, i know this is not best practice
        # please handle properly when you have time
        except AyoconnectApiError as error:
            self.sentry_client.capture_exceptions()
            logger.error({
                'function': 'AyoconnectService -> check_disburse_status()',
                'error': str(error.message)
            })
            is_retrying = False
            response = error.message

        return is_retrying, response

    def check_disburse_status(self, application_id, pg_cust_data, a_correlation_id, disbursement,
                              n_retry=1):
        payment_gateway_vendor = self.get_payment_gateway()
        log_data = {
            "payment_gateway_vendor_id": payment_gateway_vendor.id,
            "customer_id": pg_cust_data.customer_id,
            "application_id": application_id
        }

        try:
            token_response = self.client.get_token(log_data=log_data)
            user_token = token_response.get("accessToken")
        except AyoconnectApiError as err:
            logger.error({
                'function': 'AyoconnectService -> check_disburse_status()',
                'error': err.message
            })
            raise AyoconnectServiceError(err.message)

        data = {
            'user_token': user_token,
            'ayoconnect_customer_id': pg_cust_data.external_customer_id,
            'beneficiary_id': pg_cust_data.beneficiary_id,
            'a_correlation_id': a_correlation_id,
            'reference_id': disbursement.reference_id,
            'log_data': log_data,
            'n_retry': n_retry
        }

        is_retrying, response = self.get_disbursement_status(data)

        return is_retrying, response

    def get_reason(self, status, reason):
        """get reason base on status"""
        if status == DisbursementStatus.COMPLETED:
            return 'success'
        return reason

    def process_callback_disbursement(self, data):
        response_disbursement = {}
        details = data.get('details', None)
        status_code = data.get('code', None)
        if 'status' in details:
            status = AyoconnectConst.DISBURSEMENT_MAP_STATUS[details['status']]
        else:
            status = AyoconnectConst.DISBURSEMENT_MAP_STATUS[
                AyoconnectConst.DISBURSEMENT_STATUS_FAILED]
        if status_code and int(status_code) in {
            http_status_codes.HTTP_200_OK, http_status_codes.HTTP_201_CREATED,
            http_status_codes.HTTP_202_ACCEPTED
        }:
            response_disbursement['reason'] = self.get_reason(status, data.get('message'))
            response_disbursement['status'] = status
        else:
            errors = details.get('errors')

            if errors and len(errors) > 0:
                reason = errors[0].get('details')
                error_code = errors[0].get("code")
                if error_code == AyoconnectErrorCodes.ACCOUNT_INSUFFICIENT_BALANCE:
                    status = DisbursementStatus.PENDING
                    reason = AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE

                if error_code == AyoconnectErrorCodes.SYSTEM_UNDER_MAINTENANCE:
                    reason = AyoconnectErrorReason.SYSTEM_UNDER_MAINTENANCE

                if error_code in AyoconnectErrorCodes.all_existing_error_codes():
                    disburse_id = data.get('transactionId')
                    disbursement_obj = Disbursement.objects.filter(disburse_id=disburse_id).last()
                    loan = Loan.objects.filter(
                        disbursement_id=disbursement_obj.id if disbursement_obj else None
                    ).last()
                    if loan and loan.is_j1_or_jturbo_loan():
                        # For J1 & Turbo flow, we will check retry by disbursement.reason
                        reason = error_code

                        # For J1 & Turbo flow, it will be failed & use Xfers instead of pending
                        if error_code == AyoconnectErrorCodes.ACCOUNT_INSUFFICIENT_BALANCE:
                            status = DisbursementStatus.FAILED
            else:
                reason = data.get('message')
            response_disbursement['reason'] = reason
            response_disbursement['status'] = status

        if details is not None:
            response_disbursement['amount'] = details['amount']
        return response_disbursement

    def check_beneficiary(self, customer_id, loan):
        """
        Check Beneficiary with valid account number
        """
        from juloserver.disbursement.services import get_name_bank_validation
        exists = False
        status = None
        name_bank_validation = get_name_bank_validation(loan.name_bank_validation_id)
        account_number = name_bank_validation.get('account_number')
        payment_gateway_vendor = self.get_payment_gateway()
        active_payment_gateway_customer_data = PaymentGatewayCustomerData.objects.filter(
            customer_id=customer_id,
            payment_gateway_vendor=payment_gateway_vendor,
            account_number=account_number,
        ).last()
        if active_payment_gateway_customer_data:
            exists = True
            status = active_payment_gateway_customer_data.status
        return exists, status

    def get_beneficiary_id_and_status(
        self, customer_id, phone_number, account_number, swift_bank_code
    ):
        pg_customer_data = PaymentGatewayCustomerData.objects.filter(
            payment_gateway_vendor=self.get_payment_gateway(),
            customer_id=customer_id,
            phone_number=phone_number,
            account_number=account_number,
            bank_code=swift_bank_code,
        ).last()

        beneficiary_id = pg_customer_data.beneficiary_id if pg_customer_data else None
        status = pg_customer_data.status if pg_customer_data else None

        return beneficiary_id, status

    def get_unique_id(self, disbursement_id=None):
        # check if there is disbursement_id then check last data from PaymentGatewayTransaction
        if disbursement_id:
            pg_transaction = PaymentGatewayTransaction.objects.filter(
                disbursement_id=disbursement_id,
                payment_gateway_vendor=self.get_payment_gateway()
            ).last()
            if pg_transaction and pg_transaction.status == DisbursementStatus.FAILED and \
                    pg_transaction.reason == AyoconnectErrorReason.ERROR_TRANSACTION_NOT_FOUND:
                return pg_transaction.correlation_id

        return generate_unique_id()
