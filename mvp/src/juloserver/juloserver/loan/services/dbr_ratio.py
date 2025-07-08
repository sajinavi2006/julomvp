import logging
import math
from django.db import transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from juloserver.julo.constants import FeatureNameConst, RedisLockKeyName
from juloserver.julo.context_managers import redis_lock_for_update
from juloserver.loan.constants import DBRConst
from juloserver.julo.models import Application, FeatureSetting
from juloserver.account_payment.models import AccountPayment
from juloserver.dana.models import DanaCustomerData
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.loan.models import (
    LoanDbrLog,
    AnaBlacklistDbr,
)
from juloserver.customer_module.models import CustomerDataChangeRequest
from juloserver.customer_module.constants import CustomerDataChangeRequestConst
from juloserver.payment_point.models import TransactionMethod
from juloserver.loan.services.credit_matrix_repeat import get_credit_matrix_repeat
from juloserver.julo.exceptions import JuloException
from juloserver.customer_module.services.customer_related import CustomerDataChangeRequestHandler
from juloserver.cfs.authentication import EasyIncomeWebToken

logger = logging.getLogger(__name__)


class LoanDbrSetting:
    """
    Setting for `marketing_loan_prize_counter` feature setting.
    """

    def __init__(self, application, is_dbr, first_due_date=None):
        self.application = application
        is_eligible, max_monthly_payment, map_account_payments, popup_banner = get_dbr_data(
            application, is_dbr, first_due_date=first_due_date
        )
        self.is_eligible = is_eligible
        self.max_monthly_payment = max_monthly_payment
        self.map_account_payments = map_account_payments
        self.popup_banner = popup_banner

    def is_dbr_exceeded(
        self,
        duration,
        payment_amount,
        first_payment_date,
        first_payment_amount,
    ):
        """
        Checking between monthly_payment, first monthly_payment and account_payment dict
        since first payment can be bigger / smaller depend on the first payment date
        will calculate payment_amount, first_payment_amount and first_payment_date
        if the data not yet calculated, but need to pass loan_amount and interest_rate
        """
        if not self.is_eligible:
            # No need to calculate if not eligible
            return False

        # calculating first payment since first payment have different amount
        first_date_key = first_payment_date.strftime("%Y%m")
        account_payment_value = self.map_account_payments.get(first_date_key, 0)
        if account_payment_value + first_payment_amount > self.max_monthly_payment:
            return True

        # first_payment already covered, will cover the rest of month here
        for i in range(1, duration):
            new_payment_date = first_payment_date + relativedelta(months=i - 1)
            new_date_key = new_payment_date.strftime("%Y%m")
            account_payment_value = self.map_account_payments.get(new_date_key, 0)
            if account_payment_value + payment_amount > self.max_monthly_payment:
                return True

        return False

    def get_max_account_payment(self, duration, first_payment_date):
        first_date_key = first_payment_date.strftime("%Y%m")
        max_account_payment = self.map_account_payments.get(first_date_key, 0)

        for i in range(1, duration):
            new_payment_date = first_payment_date + relativedelta(months=i)
            new_date_key = new_payment_date.strftime("%Y%m")
            account_payment_value = self.map_account_payments.get(new_date_key, 0)
            if account_payment_value > max_account_payment:
                max_account_payment = account_payment_value

        return max_account_payment

    def log_dbr(self, loan_amount, duration, transaction_method_id, source):
        max_installment = 0
        today_date = timezone.localtime(timezone.now()).date()
        if self.map_account_payments:
            max_installment = max(self.map_account_payments.values())

        if source == DBRConst.LOAN_CREATION:
            # will always create log on loan creation process
            LoanDbrLog.objects.create(
                application_id=self.application.id,
                loan_amount=loan_amount,
                duration=duration,
                transaction_method_id=transaction_method_id,
                monthly_income=self.application.monthly_income,
                monthly_installment=max_installment,
                source=source,
                log_date=today_date,
            )
        else:
            # only insert once per day
            with redis_lock_for_update(
                key_name=RedisLockKeyName.CREATE_LOAN_DBR_LOG,
                unique_value="{}{}".format(self.application.id, source),
            ):
                LoanDbrLog.objects.get_or_create(
                    application_id=self.application.id,
                    log_date=today_date,
                    source=source,
                    defaults={
                        'loan_amount': loan_amount,
                        'duration': duration,
                        'transaction_method_id': transaction_method_id,
                        'monthly_income': self.application.monthly_income,
                        'monthly_installment': max_installment,
                    },
                )

    def update_popup_banner(self, self_bank_account, transaction_type_code):
        """
        pass parameter to popup banner
        this function seperated because not all dbr process using popup banner
        will pass self_bank_account and transaction_type_code alongside with token
        token using Bearer Auth
        self_bank_account is int (0/1)
        transaction_type_code is int
        """
        token = EasyIncomeWebToken.generate_token_from_user(self.application.customer.user)  # noqa
        self_bank_account = int(self_bank_account)
        link = self.popup_banner.get(DBRConst.ADDITIONAL_INFORMATION, {}).get(DBRConst.LINK, "")
        if link:
            for key, value in DBRConst.LINK_PLACEHOLDER.items():
                link = link.replace(key, str(eval(value)))
            self.popup_banner[DBRConst.ADDITIONAL_INFORMATION][DBRConst.LINK] = link

    def get_popup_banner_url(self):
        return self.popup_banner.get(DBRConst.ADDITIONAL_INFORMATION, {}).get(DBRConst.LINK, "")


def get_dbr_status_and_param_after_whitelist(application_id=None, customer_id=None):
    """
    returning is_active, parameters
    this function will also check the whitelist before returning the value
    also replacing the percentage in popup content with FS percentage
    (so when income_percentage change in the future, user only need to change it once)
    """
    dbr_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DBR_RATIO_CONFIG,
        is_active=True,
    ).last()

    if not dbr_fs:
        parameters = DBRConst.DEFAULT_PARAMETERS
        return False, parameters

    parameters = dbr_fs.parameters
    popup_banner = parameters.get("popup_banner", DBRConst.DEFAULT_POPUP_BANNER)
    income_percentage = parameters.get("ratio_percentage", DBRConst.DEFAULT_INCOME_PERCENTAGE)
    if DBRConst.CONTENT_KEY in popup_banner:
        """
        replacing empty bracket {} with current FS, so if there's percentage update,
        no need to update the message
        """
        popup_banner[DBRConst.CONTENT_KEY] = popup_banner[DBRConst.CONTENT_KEY].format(
            str(income_percentage)
        )

    whitelist = parameters.get("whitelist", {})
    is_whitelisted = whitelist.get('is_active', False)
    whitelisted_application_ids = whitelist.get('list_application_ids', [])
    if is_whitelisted and application_id not in whitelisted_application_ids:
        # Whitelist on but app_id is not whitelisted, same with inactive
        return False, parameters

    if not (is_whitelisted and application_id in whitelisted_application_ids):
        blacklist = parameters.get("blacklist", {})
        if (
            blacklist.get('is_active')
            and AnaBlacklistDbr.objects.filter(customer_id=customer_id).exists()
        ):
            # application is blacklisted, wont receive DBR
            return False, parameters

    return True, parameters


def get_dbr_data(application, is_dbr=True, first_due_date=None):
    """
    returning is_eligible, max_monthly_payment, FS parameters
    After checking FS, will check further if rule are violated
    if rule are not violated, is_eligible will be changed to True
    also skip checking if application status <= 120
    """
    is_eligible = False
    if not (
        is_dbr
        and application
        and application.application_status_id > ApplicationStatusCodes.DOCUMENTS_SUBMITTED
    ):
        return is_eligible, 0, {}, {"is_active": False}

    customer_id = application.customer_id
    is_dbr_active, dbr_parameters = get_dbr_status_and_param_after_whitelist(
        application_id=application.id, customer_id=customer_id
    )
    popup_banner = dbr_parameters.get('popup_banner')

    if not is_dbr_active:
        # FS inactive or whitelist is on and apps is not whitelisted
        return is_eligible, 0, {}, popup_banner

    product_line = application.product_line
    if product_line and product_line.product_line_code not in dbr_parameters.get(
        'product_line_ids', []
    ):
        return is_eligible, 0, {}, popup_banner

    logger.info(
        {
            "action": "juloserver.loan.services.dbr_ratio.get_dbr_data",
            "application_id": application.id,
            "customer_id": customer_id,
        }
    )

    monthly_income = get_monthly_income(application)

    # calculate j1 due_amount each month and map it with dana (if there was dana loan)
    other_account_ids = []
    other_dana_account_ids = []
    if hasattr(application, "dana_customer_data"):
        dana_customer_data = application.dana_customer_data
        nik = dana_customer_data.nik
        other_dana_account_ids = (
            DanaCustomerData.objects.filter(nik=dana_customer_data.nik)
            .values_list("account_id", flat=True)
            .exclude(id=dana_customer_data.id)
        )
        other_account_ids = (
            Application.objects.filter(
                ktp=nik, application_status=ApplicationStatusCodes.LOC_APPROVED
            )
            .values_list("account_id", flat=True)
            .exclude(id=application.id)
        )
        other_account_ids = list(other_account_ids) + list(other_dana_account_ids)
    else:
        # This to get Dana Account ID if the application is J1
        other_account_ids = DanaCustomerData.objects.filter(nik=application.ktp).values_list(
            "account_id", flat=True
        )
        other_account_ids = list(other_account_ids)

    filter_account_ids = [application.account_id] + other_account_ids

    if first_due_date:
        due_date = first_due_date
    else:
        due_date = timezone.localtime(timezone.now()).date()

    account_payments = AccountPayment.objects.filter(
        account_id__in=filter_account_ids,
        due_amount__gt=0,
        due_date__gte=due_date,
        is_restructured=False,
    ).values("due_date", "due_amount")

    # map account_payment based on month
    map_account_payments = {}
    total_monthly_payment = 0
    for account_payment in account_payments:
        due_date = account_payment.get("due_date")
        due_date_key = due_date.strftime("%Y%m")
        due_amount = account_payment.get("due_amount")
        if due_date_key not in map_account_payments:
            # initialize amount with 0
            map_account_payments[due_date_key] = 0

        map_account_payments[due_date_key] += due_amount
        total_account_payment = map_account_payments[due_date_key]
        if total_account_payment > total_monthly_payment:
            total_monthly_payment = total_account_payment

    is_eligible = True
    max_monthly_income_percentage = dbr_parameters.get('ratio_percentage')
    max_monthly_payment = monthly_income * max_monthly_income_percentage / 100

    """
    enable 'Pay' Button, if there unpaid account payment
    if active, will check unpaid payment and disable it if no unpaid_payment
    if not active, no checks will be done.
    """
    pay_button_idx = None
    buttons = popup_banner.get(DBRConst.BUTTON_KEY)
    for idx, button in enumerate(buttons):
        if button['title'] == DBRConst.PAY_BUTTON_TITLE:
            pay_button_idx = idx

    if popup_banner[DBRConst.BUTTON_KEY][pay_button_idx]['is_active']:
        account = application.account
        unpaid_payments = None

        if account:
            unpaid_payments = account.get_unpaid_account_payment_ids()

        if not unpaid_payments:
            popup_banner[DBRConst.BUTTON_KEY][pay_button_idx]['is_active'] = False

    return is_eligible, max_monthly_payment, map_account_payments, popup_banner


def get_monthly_income(application):
    # check with largest income from CustomerDataChangeRequest table
    monthly_income = application.monthly_income
    customer_data_change = (
        CustomerDataChangeRequest.objects.filter(
            application_id=application.id,
            status__in=[
                CustomerDataChangeRequestConst.SubmissionStatus.APPROVED,
            ],
        )
        .order_by('-monthly_income')
        .first()
    )

    if customer_data_change and customer_data_change.monthly_income > monthly_income:
        # check from customer data change request, and use it if salary is bigger
        monthly_income = customer_data_change.monthly_income

    return monthly_income


def calculate_new_monthly_income(data, user):
    from juloserver.loan.services.loan_related import (
        get_credit_matrix_and_credit_matrix_product_line,
    )

    logger.info(
        {
            "action": "juloserver.loan.services.dbr_ratio.calculate_new_monthly_income",
            "data": data,
            "user": user,
        }
    )

    account = user.customer.account
    self_bank_account = data.get('self_bank_account', False)
    if not account:
        raise JuloException(
            {
                'action': 'juloserver.loan.services.dbr_ratio.calculate_new_monthly_income',
                'message': 'Account tidak ditemukan',
            }
        )

    application = account.get_active_application()
    if not application:
        return {'error': 'Aplikasi tidak ditemukan'}

    account_limit = account.accountlimit_set.last()
    transaction_method_id = data.get('transaction_type_code')
    transaction_type = None
    if transaction_method_id:
        transaction_method = TransactionMethod.objects.filter(id=transaction_method_id).last()
        if transaction_method:
            transaction_type = transaction_method.method

    (credit_matrix, credit_matrix_product_line,) = get_credit_matrix_and_credit_matrix_product_line(
        application,
        is_self_bank_account=self_bank_account,
        payment_point=None,
        transaction_type=transaction_type,
    )
    if not credit_matrix or not credit_matrix.product:
        return {'error': 'Produk tidak ditemukan'}

    credit_matrix_repeat = get_credit_matrix_repeat(
        account.customer.id,
        credit_matrix_product_line.product.product_line_code,
        transaction_method_id,
    )
    monthly_interest_rate = credit_matrix.product.monthly_interest_rate
    if credit_matrix_repeat:
        monthly_interest_rate = credit_matrix_repeat.interest
    set_limit = account_limit.set_limit

    new_monthly_salary = (set_limit / 2 + (set_limit * monthly_interest_rate)) * 2
    new_monthly_salary = (
        math.ceil(new_monthly_salary / DBRConst.MONTHLY_SALARY_ROUNDING)
        * DBRConst.MONTHLY_SALARY_ROUNDING
    )
    old_monthly_salary = get_monthly_income(application)

    if old_monthly_salary >= new_monthly_salary:
        return {'error': DBRConst.MONTHLY_SALARY_ERROR}

    result = {
        'monthly_salary': old_monthly_salary,
        'new_monthly_salary': new_monthly_salary,
        'error': None,
    }
    return result


def create_new_monthly_income(customer, new_monthly_salary):
    logger.info(
        {
            "action": "juloserver.loan.services.dbr_ratio.create_new_monthly_income",
            "customer": customer,
            "new_monthly_salary": new_monthly_salary,
        }
    )

    with transaction.atomic():
        try:
            handler = CustomerDataChangeRequestHandler(customer)
            customer_data = handler.convert_application_data_to_change_request()
            customer_data.monthly_income = new_monthly_salary
            customer_data.approval_note = DBRConst.MONTHLY_SALARY_APPROVAL_NOTE
            customer_data.source = CustomerDataChangeRequestConst.Source.DBR
            customer_data.status = CustomerDataChangeRequestConst.SubmissionStatus.APPROVED
            customer_data.address.save()
            customer_data.save()
        except Exception:
            raise JuloException(
                {
                    'action': 'juloserver.loan.services.dbr_ratio.create_new_monthly_income',
                    'message': DBRConst.MONTHLY_SALARY_ERROR,
                }
            )


def get_loan_max_duration(loan_amount, credit_matrix_max_duration):
    # Calculate max duration from feature setting
    max_duration = credit_matrix_max_duration
    max_duration_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LOAN_MAX_ALLOWED_DURATION,
        is_active=True,
    ).last()
    """
    update if max duration in FS is lower than CM,
    max duration used for DBR check to append maximum available duration
    """
    if max_duration_fs:
        sorted_params = sorted(max_duration_fs.parameters, key=lambda i: i['min_amount'])
        for params in sorted_params:
            index = sorted_params.index(params)
            is_valid = params['min_amount'] < loan_amount <= params['max_amount']
            if index == 0:
                is_valid = params['min_amount'] <= loan_amount <= params['max_amount']

            if is_valid and max_duration > params['duration']:
                max_duration = params['duration']

    return max_duration
