from builtins import object
from builtins import str
from email.utils import formatdate
import uuid

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from juloserver.julo.models import Application, Loan, Payment, Bank, Document
from juloserver.disbursement.models import Disbursement, NameBankValidation

from juloserver.grab.clients.request_objects import ApplicationCreationRequest, ApplicationDetails, \
    DisbursalCreationRequest, LoanDetails, PaymentDetails, LoanCreationRequest, CaptureLoanDetails, \
    ApplicationBodyRequest, CancelLoanRequest, CancelLoanDetails, ApplicationUpdateRequest, \
    PushNotificationRequest, RepaymentTriggerObject, LoanSyncObject
from juloserver.grab.utils import GrabUtils
from juloserver.grab.clients.paths import GrabPaths
from juloserver.grab.models import GrabLoanData, GrabCustomerData
from juloserver.julo.statuses import PaymentStatusCodes, ApplicationStatusCodes, LoanStatusCodes
from juloserver.grab.constants import grab_status_mapping_statuses, GrabUserType
from juloserver.julo.constants import WorkflowConst
from juloserver.disbursement.constants import DisbursementVendors


class GrabRequestDataConstructor(object):
    POST = "POST"
    GET = "GET"
    PUT = "PUT"

    APPLICATION_CODE = "JULO_CASH_LOANS"
    APPLICATION_MODE = "ONLINE"

    DEFAULT_STATUS_LABEL = "Undefined"

    @staticmethod
    def create_msg_id():
        return str(uuid.uuid4().hex)

    @staticmethod
    def create_transaction_id():
        return str(uuid.uuid4().hex)

    @staticmethod
    def create_repayment_transaction_id():
        return str(uuid.uuid4().hex)

    @staticmethod
    def construct_headers_request(method, uri_path, phone_number, message=""):
        date = formatdate(localtime=False, usegmt=True)

        headers = {
            "Authorization": "{}:{}".format(settings.GRAB_CLIENT_ID, GrabUtils.create_signature(message,
                                                                                                method,
                                                                                                uri_path,
                                                                                                date)),
            "X-Client-Id": settings.GRAB_CLIENT_NAME,
            "User-Token": GrabUtils.create_user_token(phone_number),
            "Date": date
        }

        if method in {GrabRequestDataConstructor.POST, GrabRequestDataConstructor.PUT}:
            headers["Content-Type"] = "application/json"

        return headers

    @staticmethod
    def construct_application_creation_request(application_id):
        application = Application.objects.get_or_none(id=application_id)

        application_creation_request = ApplicationCreationRequest()
        application_creation_request.application_code = GrabRequestDataConstructor.APPLICATION_CODE
        application_creation_request.application_description = application.loan_purpose_desc
        application_creation_request.application_id = str(application.application_xid)
        application_creation_request.application_status = GrabRequestDataConstructor.\
            get_application_status_grab(application)
        application_creation_request.application_mode = GrabRequestDataConstructor.APPLICATION_MODE

        application_creation_request.application_details = GrabRequestDataConstructor. \
            _construct_application_details(application)

        application_request = ApplicationBodyRequest()
        application_request.body = application_creation_request.to_dict()
        application_request.msg_id = GrabRequestDataConstructor.create_msg_id()

        headers = GrabRequestDataConstructor.construct_headers_request(GrabRequestDataConstructor.POST,
                                                                       GrabPaths.APPLICATION_CREATION,
                                                                       application.customer.phone,
                                                                       application_request.to_json())

        return application_request, headers


    @staticmethod
    def construct_application_updation_request(application_id):
        application = Application.objects.get_or_none(id=application_id)

        application_request = ApplicationBodyRequest()
        application_update_request = ApplicationUpdateRequest()
        application_update_request.application_description = application.loan_purpose_desc
        application_update_request.application_id = str(application.application_xid)
        application_update_request.application_details = GrabRequestDataConstructor. \
            _construct_application_details(application)
        application_update_request.application_status = GrabRequestDataConstructor.\
            get_application_status_grab(application)
        application_request.msg_id = GrabRequestDataConstructor.create_msg_id()
        application_request.body = application_update_request
        headers = GrabRequestDataConstructor.construct_headers_request(GrabRequestDataConstructor.PUT,
                                                                       GrabPaths.APPLICATION_UPDATION,
                                                                       application.customer.phone,
                                                                       application_request.to_json())

        return application_request, headers

    @staticmethod
    def construct_loan_creation_request(loan_id, txn_id):
        loan = Loan.objects.get_or_none(id=loan_id)
        application = Application.objects.filter(account=loan.account).last()

        loan_creation_request = LoanCreationRequest()
        loan_creation_request.application_code = GrabRequestDataConstructor.APPLICATION_CODE
        loan_creation_request.application_description = application.loan_purpose_desc
        loan_creation_request.application_id = str(application.application_xid)
        loan_creation_request.application_status = GrabRequestDataConstructor.\
            get_application_status_grab(application)
        loan_creation_request.application_mode = GrabRequestDataConstructor.APPLICATION_MODE

        loan_creation_request.application_details = GrabRequestDataConstructor. \
            _construct_application_details(application)

        loan_creation_request.loan_details = GrabRequestDataConstructor._construct_loan_details(
            loan, application, " ", txn_id)

        transaction_id = loan_creation_request.loan_details.transaction_id

        loan_creation_request.msg_id = GrabRequestDataConstructor.create_msg_id()

        headers = GrabRequestDataConstructor.construct_headers_request(GrabRequestDataConstructor.POST,
                                                                       GrabPaths.LOAN_CREATION,
                                                                       application.customer.phone,
                                                                       loan_creation_request.to_json())

        return loan_creation_request, headers, transaction_id

    @staticmethod
    def construct_disbursal_creation_request(disbursement_id, txn_id):
        disbursement = Disbursement.objects.get_or_none(id=disbursement_id)
        loan = Loan.objects.get_or_none(disbursement_id=disbursement_id)
        application = Application.objects.get_or_none(account=loan.account)

        grab_loan_data = GrabLoanData.objects.get_or_none(loan=loan)
        if not grab_loan_data or not grab_loan_data.grab_loan_inquiry:
            return

        disbursal_creation_request = DisbursalCreationRequest()
        disbursal_creation_request.msg_id = GrabRequestDataConstructor.create_msg_id()
        disbursal_creation_request.loan_details = \
            GrabRequestDataConstructor._construct_capture_loan_details(loan, disbursement, txn_id)

        transaction_id = disbursal_creation_request.loan_details.transaction_id

        headers = GrabRequestDataConstructor.construct_headers_request(GrabRequestDataConstructor.POST,
                                                                       GrabPaths.DISBURSAL_CREATION,
                                                                       application.customer.phone,
                                                                       disbursal_creation_request.to_json())

        return disbursal_creation_request, headers, transaction_id

    @staticmethod
    def construct_cancel_loan_request(loan_id, txn_id):
        loan = Loan.objects.get_or_none(id=loan_id)
        application = Application.objects.get_or_none(account=loan.account)

        grab_loan_data = GrabLoanData.objects.get_or_none(loan=loan)
        if not grab_loan_data or not grab_loan_data.grab_loan_inquiry:
            return

        cancel_loan_request = CancelLoanRequest()
        cancel_loan_request.msg_id = GrabRequestDataConstructor.create_msg_id()
        cancel_loan_request.loan_details = \
            GrabRequestDataConstructor._construct_cancel_loan_details(loan, txn_id)

        transaction_id = cancel_loan_request.loan_details.transaction_id

        headers = GrabRequestDataConstructor.construct_headers_request(GrabRequestDataConstructor.POST,
                                                                       GrabPaths.CANCEL_LOAN,
                                                                       application.customer.phone,
                                                                       cancel_loan_request.to_json())

        return cancel_loan_request, headers, transaction_id

    @staticmethod
    def construct_loan_sync_api_request(loan_id):
        loan = Loan.objects.get_or_none(id=loan_id)

        loan_sync_request = LoanSyncObject()
        loan_sync_request.msg_id = GrabRequestDataConstructor.create_msg_id()
        loan_sync_request.loan_id = str(loan.loan_xid)
        loan_sync_request.time_stamp = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S.%f")

        headers = GrabRequestDataConstructor.construct_headers_request(GrabRequestDataConstructor.PUT,
                                                                       GrabPaths.LOAN_SYNC_API,
                                                                       loan.customer.phone,
                                                                       loan_sync_request.to_json())

        return loan_sync_request, headers

    @staticmethod
    def construct_push_notification_request(application_id, loan_id):
        application = None
        loan = None
        if application_id:
            application = Application.objects.select_related(
                'customer', 'application_status', 'workflow').filter(id=application_id).last()
            customer = application.customer
            if not application.is_grab():
                return
        else:
            loan = Loan.objects.filter(id=loan_id).last()
            customer = loan.customer
        grab_customer_data = GrabCustomerData.objects.filter(
            customer=customer).last()
        if not grab_customer_data:
            return

        push_notification_request = PushNotificationRequest()
        push_notification_request.msg_id = GrabRequestDataConstructor.create_msg_id()
        push_notification_request.language = "ID"
        push_notification_request.notification_type = "push"
        push_notification_request.event = \
            GrabRequestDataConstructor._construct_push_notification_event(
                application, loan)
        push_notification_request.meta = \
            GrabRequestDataConstructor._construct_push_notification_meta(customer)
        push_notification_request.user_id = grab_customer_data.hashed_phone_number
        push_notification_request.user_id_type = "hash_phone_number"
        push_notification_request.user_type = GrabUserType.DAX

        headers = GrabRequestDataConstructor.construct_headers_request(GrabRequestDataConstructor.POST,
                                                                       GrabPaths.PUSH_NOTIFICATION,
                                                                       customer.phone,
                                                                       push_notification_request.to_json())

        return push_notification_request, headers

    @staticmethod
    def _construct_application_details(application):
        application_details = ApplicationDetails()
        application_details.bank_account_number = application.bank_account_number
        application_details.bank_name = application.bank_name
        application_details.birth_place = application.birth_place
        application_details.company_name = application.company_name
        application_details.dependents = application.dependent
        application_details.district = application.address_kabupaten
        application_details.domicile_status = application.home_status
        application_details.gender = application.gender
        application_details.job_description = application.job_description
        application_details.job_industry = application.job_industry
        application_details.job_type = application.job_type
        application_details.last_education = application.last_education
        application_details.loan_purpose = application.loan_purpose
        application_details.marital_status = application.marital_status
        application_details.monthly_expenses = application.monthly_expenses
        application_details.monthly_housing_cost = application.monthly_housing_cost
        application_details.monthly_income = application.monthly_income
        application_details.occupied_since = application.occupied_since
        application_details.province = application.address_provinsi
        application_details.start_work_date = application.job_start
        application_details.sub_district1 = application.address_kecamatan
        application_details.sub_district2 = application.address_kelurahan

        """ this payment_status_codes is equal with payment_status_code < PAID_ON_TIME (330) """
        payment_status_codes_lt_330 = [
            PaymentStatusCodes.PAYMENT_180DPD,
            PaymentStatusCodes.PAYMENT_150DPD,
            PaymentStatusCodes.PAYMENT_120DPD,
            PaymentStatusCodes.PAYMENT_90DPD,
            PaymentStatusCodes.PAYMENT_60DPD,
            PaymentStatusCodes.PAYMENT_30DPD,
            PaymentStatusCodes.PAYMENT_5DPD,
            PaymentStatusCodes.PAYMENT_1DPD,
            PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
            PaymentStatusCodes.PAYMENT_DUE_TODAY,
            PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
            PaymentStatusCodes.PAYMENT_NOT_DUE,
        ]
        total_due_amount = 0
        """
            Application will have account at status 141.
        """
        if application.account_id and application.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
            loan_ids = Loan.objects.filter(account_id=application.account_id).values_list('id', flat=True)
            list_due_amount = Payment.objects.filter(
                payment_status__status_code__in=payment_status_codes_lt_330,
                loan_id__in=loan_ids).values_list('due_amount', flat=True)
            for due_amount in list_due_amount.iterator():
                total_due_amount += due_amount
        application_details.total_current_debt = total_due_amount

        return application_details

    @staticmethod
    def _construct_loan_details(loan, application, sphp_url, txn_id):
        grab_loan_data = GrabLoanData.objects.get_or_none(loan=loan)
        if not grab_loan_data or not grab_loan_data.grab_loan_inquiry:
            return

        name_bank_validation = NameBankValidation.objects.get_or_none(
            pk=loan.name_bank_validation_id)
        if not name_bank_validation:
            return
        bank_code = name_bank_validation.bank_code
        swift_bank_code = ''
        if bank_code:
            filter_param = {}
            if name_bank_validation.method == DisbursementVendors.PG:
                filter_param['id'] = name_bank_validation.bank_id
            else:
                filter_param["xfers_bank_code"] = bank_code

            swift_bank_code = Bank.objects.filter(**filter_param).last()
            if swift_bank_code:
                swift_bank_code = swift_bank_code.swift_bank_code
            else:
                swift_bank_code = ''
        if not txn_id:
            transaction_id = GrabRequestDataConstructor.create_transaction_id()
        else:
            transaction_id = txn_id
        loan_details = LoanDetails()
        loan_details.program_id = grab_loan_data.program_id if grab_loan_data else 0
        loan_details.loan_id = str(loan.loan_xid)
        loan_details.loan_amount = loan.loan_amount
        loan_details.loan_duration = loan.loan_duration
        loan_details.payment_details = GrabRequestDataConstructor._construct_payment_details(loan)
        loan_details.loan_agreement_url = 'None'  # TODO: get privy loan agreement url
        loan_details.loan_application_date = loan.cdate
        loan_details.transaction_id = transaction_id  # TODO: need to ask grab what is this field?
        loan_details.loan_agreement_url = sphp_url
        loan_details.loan_application_date = loan.sphp_sent_ts
        loan_details.currency = "IDR"
        loan_details.frequency = loan.account.account_lookup.payment_frequency
        loan_details.bank_code = swift_bank_code
        loan_details.bank_account_number = application.bank_account_number
        loan_details.application_id = str(application.application_xid)
        loan_details.interest_amount = round(loan.product.interest_rate * 100, 2)
        loan_details.fees_amount = grab_loan_data.selected_fee
        loan_details.interest_value_period = loan.loan_duration

        loan_details.loan_status = loan.loan_status.status
        loan_details.weekly_instalment_amount = round(grab_loan_data.grab_loan_inquiry.weekly_instalment_amount, 2)
        loan_details.collection_amount = loan.payment_set.aggregate(Sum(
            'due_amount'))['due_amount__sum']
        loan_details.interest_amount_period = loan.loan_duration

        return loan_details

    @staticmethod
    def _construct_payment_details(loan):
        payments = Payment.objects.filter(loan=loan).order_by('payment_number')

        payment_details = []
        for index, payment in enumerate(payments):
            payment_detail = PaymentDetails()
            payment_detail.payment_id = str(payment.id)
            payment_detail.payment_number = payment.payment_number
            payment_detail.due_amount = payment.due_amount
            payment_detail.principal_amount = payment.installment_principal
            payment_detail.interest_amount = payment.installment_interest
            payment_detail.fees_amount = payment.late_fee_amount
            payment_detail.due_date = payment.due_date
            payment_detail.paid_date = payment.paid_date
            payment_detail.transaction_id = GrabRequestDataConstructor.create_transaction_id()

            payment_details.append(payment_detail)

        return payment_details

    @staticmethod
    def _construct_capture_loan_details(loan, disbursement, txn_id):
        grab_loan_data = GrabLoanData.objects.get_or_none(loan=loan)
        if not grab_loan_data or not grab_loan_data.grab_loan_inquiry:
            return

        loan_details = CaptureLoanDetails()
        loan_details.program_id = grab_loan_data.program_id if grab_loan_data else 0
        loan_details.loan_id = str(loan.loan_xid)
        loan_details.loan_amount = loan.loan_amount
        loan_details.fees_amount = grab_loan_data.grab_loan_inquiry.fee_value
        loan_details.interest_amount = round(loan.product.interest_rate * 100, 2)
        loan_details.frequency = loan.account.account_lookup.payment_frequency  # TODO: Fix Value
        loan_details.weekly_instalment_amount = round(grab_loan_data.grab_loan_inquiry.weekly_instalment_amount, 2)
        loan_details.fund_transfer_timestamp = disbursement.cdate
        loan_details.loan_disbursement_amount = disbursement.amount
        loan_details.loan_disbursement_date = loan.disbursement_date
        loan_details.currency = "IDR"
        if not txn_id:
            loan_details.transaction_id = GrabRequestDataConstructor.create_transaction_id()
        else:
            loan_details.transaction_id = txn_id
        loan_details.auth_transaction_id = grab_loan_data.auth_transaction_id
        loan_details.program_id = grab_loan_data.program_id
        loan_details.txn_type = 'AUTH_CAPTURE'
        loan_details.loan_status = loan.loan_status.status
        loan_details.collection_amount = int(loan.payment_set.aggregate(Sum(
            'installment_principal'))['installment_principal__sum']) + int(
            loan.payment_set.aggregate(Sum(
                'installment_interest'))['installment_interest__sum'])
        loan_details.interest_amount_period = loan.loan_duration
        loan_details.loan_duration = loan.loan_duration

        return loan_details

    @staticmethod
    def _construct_cancel_loan_details(loan, txn_id):
        grab_loan_data = GrabLoanData.objects.get_or_none(loan=loan)
        if not grab_loan_data or not grab_loan_data.grab_loan_inquiry:
            return

        loan_details = CancelLoanDetails()
        loan_details.loan_id = str(loan.loan_xid)
        loan_details.application_id = str(loan.account.last_application.id)
        loan_details.loan_amount = loan.loan_amount
        loan_details.fees_amount = grab_loan_data.grab_loan_inquiry.fee_value
        loan_details.frequency = loan.account.account_lookup.payment_frequency
        loan_details.weekly_instalment_amount = round(grab_loan_data.grab_loan_inquiry.weekly_instalment_amount, 2)
        loan_details.interest_amount = round(loan.product.interest_rate * 100, 2)
        loan_details.loan_disbursement_amount = 0
        loan_details.currency = "IDR"
        loan_details.loan_status = loan.loan_status.status
        if not txn_id:
            loan_details.transaction_id = GrabRequestDataConstructor.create_transaction_id()
        else:
            loan_details.transaction_id = txn_id
        loan_details.auth_transaction_id = grab_loan_data.auth_transaction_id
        loan_details.program_id = grab_loan_data.program_id
        loan_details.interest_amount_period = loan.loan_duration
        loan_details.loan_duration = loan.loan_duration
        loan_details.txn_type = 'AUTH_CANCEL'
        loan_details.collection_amount = int(loan.payment_set.aggregate(Sum(
            'installment_principal'))['installment_principal__sum']) + int(
            loan.payment_set.aggregate(Sum(
                'installment_interest'))['installment_interest__sum'])

        return loan_details

    @staticmethod
    def get_application_status_grab(application):
        grab_status_mapping = 'Invalid status'
        for grab_status in grab_status_mapping_statuses:
            if application.application_status_id == grab_status.list_code:
                if application.application_status_id != ApplicationStatusCodes.LOC_APPROVED:
                    grab_status_mapping = grab_status.mapping_status
                else:
                    if Loan.objects.filter(
                            account=application.account).exclude(
                        loan_status__in=[
                            LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
                            LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD,
                            LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
                            LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
                            LoanStatusCodes.LOAN_180DPD, LoanStatusCodes.RENEGOTIATED,
                            241
                        ]
                    ).exists():
                        additional_check = 'Inactive Loan'
                    else:
                        additional_check = 'No Inactive Loan'
                    if grab_status.additional_check == additional_check:
                        grab_status_mapping = grab_status.mapping_status
        return grab_status_mapping

    @staticmethod
    def _construct_push_notification_event(application, loan):
        if application:
            mapping_status = GrabRequestDataConstructor.\
                get_application_status_grab(application)
            event = "julo||loan_application||{}".format(mapping_status)
        else:
            mapping_status = loan.loan_status.status
            event = "julo||loan_status||{}".format(mapping_status)
        return event

    @staticmethod
    def _construct_push_notification_meta(customer):
        from juloserver.grab.services.services import get_expiry_date_grab
        applied_amount = None
        application = customer.application_set.filter(workflow__name=WorkflowConst.GRAB).last()
        if customer:
            grab_customer_data = GrabCustomerData.objects.filter(customer=customer).last()
            grab_loan_inquiry = grab_customer_data.grabloaninquiry_set.last()
            if grab_loan_inquiry:
                grab_loan_data = grab_loan_inquiry.grabloandata_set.last()
                if grab_loan_data:
                    applied_amount = grab_loan_data.selected_amount
        meta_dict = {
            "expiry_date": get_expiry_date_grab(application),
            "applied_amount": applied_amount
        }
        return meta_dict

    @staticmethod
    def contruct_repayment_trigger_api(loan_id, grab_txn, customer, overdue_amount=None):
        repayment_trigger_obj = RepaymentTriggerObject()
        repayment_trigger_obj.loan_id = str(loan_id)
        repayment_trigger_obj.txn_id = grab_txn.id
        repayment_trigger_obj.msg_id = GrabRequestDataConstructor.create_msg_id()
        if overdue_amount:
            repayment_trigger_obj.overdue_amount = overdue_amount

        headers = GrabRequestDataConstructor.construct_headers_request(
            GrabRequestDataConstructor.POST,
            GrabPaths.DEDUCTION_API,
            customer.phone,
            repayment_trigger_obj.to_json())
        return repayment_trigger_obj, headers
