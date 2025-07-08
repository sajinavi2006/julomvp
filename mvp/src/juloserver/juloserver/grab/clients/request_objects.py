from builtins import object
import json
import datetime


class PlainObject(object):
    def __init__(self):
        pass

    def to_json(self):
        return json.dumps(self.to_dict())

    def to_dict(self):
        return json.loads(json.dumps(self, default=lambda o: o.__dict__ if hasattr(o, "__dict__") else o.__str__()))


class DisbursalCreationRequest(PlainObject):
    application_id = None
    fund_transfer_timestamp = None
    loan_disbursement_amount = None
    transaction_id = None
    auth_reference_txn_id = None
    txn_type = None
    loan_id = None
    msg_id = None
    loan_details = None


class CancelLoanRequest(PlainObject):
    application_id = None
    fund_transfer_timestamp = None
    loan_disbursement_amount = None
    transaction_id = None
    auth_reference_txn_id = None
    txn_type = None
    loan_id = None
    msg_id = None
    loan_details = None


class PushNotificationRequest(PlainObject):
    language = None
    notification_type = None
    event = None
    meta = None
    user_id = None
    user_id_type = None
    user_type = None


class ApplicationBodyRequest(PlainObject):
    msg_id = None
    body = None


class ApplicationCreationRequest(PlainObject):
    application_code = None
    application_description = None
    application_id = None
    application_status = None
    application_mode = None
    application_details = None


class ApplicationUpdateRequest(PlainObject):
    application_description = None
    application_id = None
    application_status = None
    application_details = None


class LoanCreationRequest(ApplicationCreationRequest):
    loan_details = None
    msg_id = None
    loan_agreement_url = None
    loan_application_date = None
    currency = None
    loan_status = None
    transaction_id = None
    weekly_installment_amount = None


class ApplicationDetails(PlainObject):
    bank_account_number = None
    bank_name = None
    birth_place = None
    company_name = None
    dependents = None
    district = None
    domicile_status = None
    gender = None
    job_description = None
    job_industry = None
    job_type = None
    last_education = None
    loan_purpose = None
    marital_status = None
    monthly_expenses = None
    monthly_housing_cost = None
    monthly_income = None
    occupied_since = None
    province = None
    start_work_date = None
    sub_district1 = None
    sub_district2 = None
    total_current_debt = None


class LoanDetails(PlainObject):
    program_id = None
    loan_amount = None
    loan_duration = None
    payment_details = None
    loan_agreement_url = None
    loan_application_date = None
    transaction_id = None
    loan_id = None
    bank_code = None
    bank_account_number = None
    application_id = None
    frequency = None
    interest_amount = None
    interest_value_period = None
    fees_amount = None
    currency = None
    loan_status = None
    weekly_installment_amount = None
    collection_amount = None
    interest_amount_period = None


class PaymentDetails(PlainObject):
    payment_id = None
    payment_number = None
    due_amount = None
    principle_amount = None
    interest_amount = None
    fees_amount = None
    due_date = None
    paid_date = None
    transaction_id = None


class CaptureLoanDetails(PlainObject):
    application_id = None
    loan_amount = None
    fees_amount = None
    interest_amount = None
    frequency = None
    weekly_installment_amount = None
    fund_transfer_timestamp = None
    loan_disbursement_amount = None
    currency = None
    loan_status = None
    transaction_id = None
    auth_transaction_id = None
    program_id = None
    txn_type = None
    loan_id = None
    msg_id = None
    collection_amount = None
    interest_amount_period = None
    loan_duration = None


class CancelLoanDetails(PlainObject):
    application_id = None
    loan_amount = None
    fees_amount = None
    interest_amount = None
    frequency = None
    weekly_installment_amount = None
    fund_transfer_timestamp = None
    loan_disbursement_amount = None
    currency = None
    loan_status_id = None
    transaction_id = None
    auth_transaction_id = None
    program_id = None
    txn_type = None
    loan_id = None
    msg_id = None
    collection_amount = None
    interest_amount_period = None
    loan_duration = None


class RepaymentTriggerObject(PlainObject):
    loan_id = None
    txn_id = None
    overdue_amount = None
    request_time = None
    msg_id = None


class LoanSyncObject(PlainObject):
    loan_id = None
    msg_id = None
    time_stamp = None
