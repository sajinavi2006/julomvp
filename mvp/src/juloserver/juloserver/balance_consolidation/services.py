import typing
import json
import os
import tempfile
import uuid
import math
from PIL import Image as Imagealias
from datetime import datetime, timedelta
from babel.dates import format_date

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
import logging

from factory.django import mute_signals
from django.db.models.signals import post_save
from django.utils import timezone
from juloserver.account.services.credit_limit import update_available_limit
from django.template.loader import render_to_string
from juloserver.balance_consolidation.constants import (
    BalanceConsolidationStatus,
    BalanceConsolidationMessageException,
    ELEMENTS_IN_TOKEN,
    TOKEN_EXPIRATION_DAYS,
    BalanceConsolidationFeatureName,
    BalconLimitIncentiveConst,
)
from juloserver.balance_consolidation.models import (
    Fintech,
    BalanceConsolidationVerification,
    BalanceConsolidationVerificationHistory,
    BalanceConsolidationHistory,
    BalanceConsolidationDelinquentFDCChecking,
)
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import BankAccountCategory, BankAccountDestination
from juloserver.graduation.constants import GraduationType, DowngradeType
from juloserver.graduation.services import (
    update_post_graduation_for_balance_consolidation,
    run_downgrade_limit,
)

from juloserver.julo.constants import PaymentEventConst
from juloserver.julo.models import (
    Document,
    Bank,
    FeatureSetting,
    Image,
    PaymentMethod,
    Payment,
    PaymentEvent,
    PaymentNote,
    CreditMatrixRepeatLoan,
    FDCInquiry,
    FDCInquiryLoan,
)
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.tasks import upload_document, send_pn_invalidate_caching_loans_android
from juloserver.julo.utils import (
    execute_after_transaction_safely,
    upload_file_to_oss,
    display_rupiah_skrtp,
    construct_customize_remote_filepath,
    display_rupiah,
)
from juloserver.disbursement.services import (
    get_list_validation_method_xfers,
    trigger_name_in_bank_validation,
)
from juloserver.julocore.customized_psycopg2.base import DatabaseError
from juloserver.account.models import (
    AccountLimit,
    Account,
    AccountLimitHistory,
    AccountTransaction,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.services.reversal import consume_reversal_for_interest
from juloserver.loan.constants import LoanPurposeConst
from juloserver.loan.services.loan_related import (
    calculate_loan_amount,
    get_loan_amount_by_transaction_type,
    generate_loan_payment_julo_one,
    transaction_fdc_risky_check,
    compute_payment_installment_julo_one,
    get_credit_matrix_and_credit_matrix_product_line,
    get_loan_duration,
    refiltering_cash_loan_duration,
    is_product_locked_for_balance_consolidation,
)
from juloserver.loan.services.lender_related import julo_one_lender_auto_matchmaking
from juloserver.loan.services.credit_matrix_repeat import get_credit_matrix_repeat
from juloserver.loan.services.sphp import accept_julo_sphp
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.balance_consolidation.exceptions import (
    BalanceConsolidationNotMatchException,
    BalanceConsolidationCanNotCreateLoan,
)
from juloserver.balance_consolidation.tasks import (
    send_pn_balance_consolidation_verification_status_approved,
)
from juloserver.balance_consolidation.constants import FeatureNameConst
from juloserver.payment_point.models import TransactionMethod
from juloserver.fdc.constants import FDCStatus
from juloserver.julo.models import Customer
from juloserver.fdc.services import get_and_save_fdc_data
from juloserver.fdc.constants import FDCReasonConst, FDCStatus
from juloserver.moengage.services.use_cases import send_event_moengage_for_balcon_punishment


logger = logging.getLogger(__name__)


class ConsolidationVerificationStatusService:
    def __init__(
        self, consolidation_verification, account: Account = None, bank_account_destination=None
    ):
        self.consolidation_verification = consolidation_verification
        self.account = account
        self.balance_consolidation = self.consolidation_verification.balance_consolidation
        self.name_bank_validation = self.consolidation_verification.name_bank_validation
        self.bank_account_destination = bank_account_destination
        self.limit_incentive_config = get_limit_incentive_config()

    @staticmethod
    def can_status_update(old_validation_status, new_validation_status):
        allow_moving_statuses = BalanceConsolidationStatus.get_allow_moving_status()
        available_statuses = allow_moving_statuses.get(old_validation_status, set())
        return new_validation_status in available_statuses

    def update_post_graduation(self):
        account_property = self.account.accountproperty_set.last()
        account_limit_histories = self.consolidation_verification.account_limit_histories
        graduation_type = GraduationType.BALANCE_CONSOLIDATION
        update_post_graduation_for_balance_consolidation(
            graduation_type, account_property, account_limit_histories['upgrade']
        )

    def update_status_abandoned(self):
        self.update_status(status=BalanceConsolidationStatus.ABANDONED)

    def update_status_cancelled(self):
        self.update_status(status=BalanceConsolidationStatus.CANCELLED)

    def update_status_disbursed(self):
        self.update_status(status=BalanceConsolidationStatus.DISBURSED)

    def update_status(self, status):
        old_validation_status = self.consolidation_verification.validation_status
        self.consolidation_verification.validation_status = status
        self.consolidation_verification.save()
        BalanceConsolidationVerificationHistory.objects.create(
            balance_consolidation_verification=self.consolidation_verification,
            field_name='validation_status',
            value_old=old_validation_status,
            value_new=status,
        )

    def _create_account_limit_history(
        self, account_limit, new_max_limit, new_available_limit, new_set_limit
    ):
        latest_affordability_history_id = account_limit.latest_affordability_history_id
        max_limit = AccountLimitHistory.objects.create(
            account_limit=account_limit,
            field_name='max_limit',
            value_old=str(account_limit.max_limit),
            value_new=str(new_max_limit),
            affordability_history_id=latest_affordability_history_id,
            credit_score_id=account_limit.latest_credit_score_id,
        )
        set_limit = AccountLimitHistory.objects.create(
            account_limit=account_limit,
            field_name='set_limit',
            value_old=str(account_limit.set_limit),
            value_new=str(new_set_limit),
            affordability_history_id=latest_affordability_history_id,
            credit_score_id=account_limit.latest_credit_score_id,
        )

        available_limit = AccountLimitHistory.objects.create(
            account_limit=account_limit,
            field_name='available_limit',
            value_old=str(account_limit.available_limit),
            value_new=str(new_available_limit),
            affordability_history_id=latest_affordability_history_id,
            credit_score_id=account_limit.latest_credit_score_id,
        )
        return dict(
            max_limit=max_limit.pk,
            available_limit=available_limit.pk,
            set_limit=set_limit.pk,
            amount_changed=(new_set_limit - account_limit.set_limit)
        )

    def handle_after_status_approved(self, amount, is_upgrade, **kwargs):
        account_limit_histories = self.consolidation_verification.account_limit_histories
        if not is_upgrade:
            amount = -amount
        account_limit = AccountLimit.objects.select_for_update().get(account=self.account)
        new_available_limit = account_limit.available_limit + amount
        new_max_limit = account_limit.max_limit + amount
        new_set_limit = account_limit.set_limit + amount

        account_limit_history_dict = self._create_account_limit_history(
            account_limit, new_max_limit, new_available_limit, new_set_limit
        )
        # Update account_limit_history_dict with kwargs
        account_limit_history_dict.update(**kwargs)
        if is_upgrade:
            account_limit_histories['upgrade'] = account_limit_history_dict
        else:
            account_limit_histories['downgrade'] = account_limit_history_dict
            self.update_status_abandoned()

        self.consolidation_verification.save()
        with mute_signals(post_save):
            account_limit.update_safely(
                max_limit=new_max_limit,
                set_limit=new_set_limit,
                available_limit=new_available_limit,
            )

    def generate_loan_balance_consolidation(self):
        application = self.account.get_active_application()
        is_payment_point = False
        data = {
            'self_bank_account': False,
            'loan_amount_request': self.balance_consolidation.loan_outstanding_amount,
            'bank_account_destination_id': self.bank_account_destination.pk,
            'loan_purpose': LoanPurposeConst.PERPINDAHAN_LIMIT,
            'loan_duration': self.balance_consolidation.loan_duration,
        }
        transaction_method_id = TransactionMethodCode.BALANCE_CONSOLIDATION.code
        transaction_method = TransactionMethod.objects.filter(id=transaction_method_id).last()
        loan_amount = data['loan_amount_request']

        if is_product_locked_for_balance_consolidation(self.account, transaction_method_id):
            raise BalanceConsolidationCanNotCreateLoan

        adjusted_loan_amount, credit_matrix, credit_matrix_product_line = calculate_loan_amount(
            application=application,
            loan_amount_requested=loan_amount,
            transaction_type=transaction_method.method,
            is_payment_point=is_payment_point,
            is_self_bank_account=data['self_bank_account'],
        )
        credit_matrix_product = credit_matrix.product
        monthly_interest_rate = credit_matrix_product.monthly_interest_rate
        origination_fee_pct = credit_matrix_product.origination_fee_pct
        # check credit matrix repeat, and if exist change the provision fee and interest
        credit_matrix_repeat = get_credit_matrix_repeat(
            self.account.customer.id,
            credit_matrix_product_line.product.product_line_code,
            transaction_method_id,
        )
        if credit_matrix_repeat:
            origination_fee_pct = credit_matrix_repeat.provision
            monthly_interest_rate = credit_matrix_repeat.interest
            # recalculate amount since origination_fee_pct may be changed
            adjusted_loan_amount = get_loan_amount_by_transaction_type(
                loan_amount, origination_fee_pct, data['self_bank_account']
            )
        loan_requested = dict(
            is_loan_amount_adjusted=True,
            original_loan_amount_requested=loan_amount,
            loan_amount=adjusted_loan_amount,
            loan_duration_request=data['loan_duration'],
            interest_rate_monthly=monthly_interest_rate,
            product=credit_matrix_product,
            provision_fee=origination_fee_pct,
            is_withdraw_funds=data['self_bank_account'],
        )
        loan_update_dict = {}
        with transaction.atomic():
            loan = generate_loan_payment_julo_one(
                application,
                loan_requested,
                data['loan_purpose'],
                credit_matrix,
                self.bank_account_destination,
            )
            if credit_matrix_repeat:
                CreditMatrixRepeatLoan.objects.create(
                    credit_matrix_repeat=credit_matrix_repeat,
                    loan=loan,
                )
                loan.set_disbursement_amount()
                loan.save()

            check_and_update_loan_balance_consolidation(loan, transaction_method_id)
            transaction_fdc_risky_check(loan)

            update_available_limit(loan)
            loan_update_dict['transaction_method'] = transaction_method
        # assign lender
        lender = julo_one_lender_auto_matchmaking(loan)
        if lender:
            loan_update_dict.update({'lender_id': lender.pk, 'partner_id': lender.user.partner.pk})
        loan.update_safely(**loan_update_dict)
        return loan

    def update_image_signature_for_loan(self, loan):
        image = self.balance_consolidation.signature_image
        image.update_safely(image_source=loan.id)

    def evaluate_increase_limit_incentive_amount(self) -> typing.Tuple[bool, dict]:
        '''
        Returns:
            - eligible (bool)
            - required_increase_info_dict (dict) include increase amount and bonus
        '''
        config = self.limit_incentive_config
        account_limit_obj = self.account.get_account_limit
        set_limit = account_limit_obj.set_limit
        available_limit = account_limit_obj.available_limit
        eligible, required_increase_info_dict = False, {}

        if set_limit < config['min_set_limit']:
            return eligible, required_increase_info_dict

        max_increase = math.ceil(set_limit * config['multiplier'])
        max_increase = min(max_increase, config['max_limit_incentive'])
        req_amount = self.balance_consolidation.loan_outstanding_amount
        increase_amount = max(req_amount - available_limit, 0)
        required_increase_info_dict['increase_amount'] = increase_amount

        if increase_amount <= max_increase:
            eligible = True

            # only add bonus if available_limit after balcon <= 500k
            if available_limit - req_amount <= config['bonus_incentive']:
                required_increase_info_dict['increase_amount'] += config['bonus_incentive']
                required_increase_info_dict['bonus_incentive'] = config['bonus_incentive']
        else:
            eligible, required_increase_info_dict = False, {}

        return eligible, required_increase_info_dict

    def check_limit_incentive(self) -> bool:
        eligible, _ = self.evaluate_increase_limit_incentive_amount()
        return eligible


def get_fintechs():
    return list(Fintech.objects.filter(is_active=True).order_by('name').values('id', 'name'))


def is_blocked_create_balance_consolidation(customer):
    return BalanceConsolidationVerification.objects.filter(
        balance_consolidation__customer=customer,
        validation_status__in=BalanceConsolidationStatus.blocked_create_statuses(),
    ).exists()


def create_balance_consolidation_verification(balance_consolidation):
    return BalanceConsolidationVerification.objects.create(
        balance_consolidation=balance_consolidation,
        validation_status=BalanceConsolidationStatus.DRAFT,
    )


def get_local_file(request_file):
    filename = 'balance_consolidation-{}-{}'.format(uuid.uuid4(), request_file.name)
    file_path = os.path.join(tempfile.mkdtemp(dir="/media"), filename)
    with open(file_path, 'wb') as f:
        f.write(request_file.read())
    return file_path, filename


def upload_loan_agreement_document(application, request_file):
    file_path, filename = get_local_file(request_file)
    document = Document.objects.create(
        document_source=application.id,
        document_type="balance_consolidation",
        filename=filename,
        application_xid=application.application_xid,
    )
    execute_after_transaction_safely(lambda: upload_document.delay(document.id, file_path))
    return document


def populate_info_for_name_bank(context, balance_consolidation):
    context['bank_list'] = Bank.objects.all().values_list('bank_name', flat=True)
    consolidation_verification = balance_consolidation.balanceconsolidationverification
    context['consolidation_verification'] = consolidation_verification
    context['name_bank_validation'] = consolidation_verification.name_bank_validation
    context['validation_method_list'] = get_list_validation_method_xfers()
    return context


def prepare_data_to_validate(data_to_validate):
    consolidation_verification = data_to_validate['consolidation_verification']
    application = consolidation_verification.balance_consolidation.customer.last_application
    data_to_validate['mobile_phone'] = application.mobile_phone_1
    data_to_validate['application'] = application
    data_to_validate['name_bank_validation_id'] = None


def validate_name_bank_validation(data_to_validate, agent):
    consolidation_verification = data_to_validate['consolidation_verification']
    old_name_bank_validation_id = consolidation_verification.name_bank_validation_id
    method = data_to_validate['validation_method']

    # validate
    validation = trigger_name_in_bank_validation(data_to_validate, method=method, new_log=True)
    name_bank_validation_id = validation.get_id()
    validation.validate()

    # update and create history
    with transaction.atomic():
        consolidation_verification.update_safely(name_bank_validation_id=name_bank_validation_id)
        consolidation_verification.refresh_from_db()
        name_bank_validation = consolidation_verification.name_bank_validation
        BalanceConsolidationVerificationHistory.objects.create(
            balance_consolidation_verification=consolidation_verification,
            agent=agent,
            field_name='name_bank_validation',
            value_old=old_name_bank_validation_id,
            value_new=name_bank_validation.pk,
        )
        return name_bank_validation


def populate_fdc_data(application, context):
    context['latest_fdc_inquiry_loans'] = []
    latest_fdc_inquiry = FDCInquiry.objects.filter(
        application_id=application.id, inquiry_status='success', status__iexact=FDCStatus.FOUND
    ).last()
    context['latest_fdc_inquiry'] = latest_fdc_inquiry

    if latest_fdc_inquiry:
        latest_fdc_inquiry_loans = (
            latest_fdc_inquiry.fdcinquiryloan_set
            .order_by('-tgl_penyaluran_dana')
            .all()
        )

        context['latest_fdc_inquiry_loans'] = latest_fdc_inquiry_loans


def create_bank_account_destination_for_kirim_dana(customer, name_bank_validation):
    category = BankAccountCategory.objects.get(
        category=BankAccountCategoryConst.BALANCE_CONSOLIDATION
    )
    bank = Bank.objects.filter(xfers_bank_code=name_bank_validation.bank_code).last()
    return BankAccountDestination.objects.create(
        bank_account_category=category,
        customer=customer,
        bank=bank,
        account_number=name_bank_validation.account_number,
        name_bank_validation_id=name_bank_validation.pk,
        description='Bank account destination only',
    )


def process_approve_balance_consolidation(verification, limit_incentive_info_dict):
    account = verification.balance_consolidation.customer.account
    bank_account_destination = create_bank_account_destination_for_kirim_dana(
        verification.balance_consolidation.customer, verification.name_bank_validation
    )
    consolidation_service = ConsolidationVerificationStatusService(
        verification, account, bank_account_destination=bank_account_destination
    )
    loan = consolidation_service.generate_loan_balance_consolidation()
    increase_amount = limit_incentive_info_dict['increase_amount']
    bonus_incentive = limit_incentive_info_dict.get('bonus_incentive', 0)

    consolidation_service.handle_after_status_approved(
        increase_amount,
        is_upgrade=True,
        bonus_incentive=bonus_incentive,
    )
    verification.update_safely(loan=loan)
    consolidation_service.update_image_signature_for_loan(loan)
    execute_after_transaction_safely(lambda: accept_julo_sphp(loan, "JULO"))
    execute_after_transaction_safely(
        lambda: send_pn_balance_consolidation_verification_status_approved.delay(
            verification.balance_consolidation.customer_id
        )
    )
    # send pn to trigger recall one-click-repeat api in FE
    execute_after_transaction_safely(
        lambda: send_pn_invalidate_caching_loans_android.delay(account.customer_id, None, None)
    )


def lock_consolidation_verification(consolidation_verification_id, agent_id):
    logger_data = {
        'module': 'balance_consolidation',
        'action': 'services.core_services.lock_consolidation_verification',
        'consolidation_verification_id': consolidation_verification_id,
        'agent_id': agent_id,
    }
    try:
        with transaction.atomic():
            balance_verification = BalanceConsolidationVerification.objects.select_for_update(
                nowait=True
            ).get(id=consolidation_verification_id)
            if balance_verification.locked_by_id:
                logger.info(
                    {
                        'message': 'The assignment is locked by another agent',
                        'locked_by_id': balance_verification.locked_by_id,
                        **logger_data,
                    }
                )
                return False

            balance_verification.locked_by_id = agent_id
            balance_verification.save(update_fields=['locked_by_id', 'udate'])
            return True
    except DatabaseError:
        logger.warning(
            {
                'message': 'The consolidation verification is locked from DB',
                **logger_data,
            },
            exc_info=True,
        )
        return False


def unlock_consolidation_verification(consolidation_verification_id):
    BalanceConsolidationVerification.objects.filter(id=consolidation_verification_id).update(
        locked_by_id=None
    )


def get_locked_consolidation_verifications(agent_id):
    return list(
        BalanceConsolidationVerification.objects.filter(locked_by_id=agent_id)
        .order_by('cdate')
        .all()
    )


def get_or_none_balance_consolidation(customer_id):
    return BalanceConsolidationVerification.objects.get_or_none(
        balance_consolidation__customer_id=customer_id,
        validation_status=BalanceConsolidationStatus.APPROVED,
        loan__isnull=True,
    )


def get_balance_consolidation_verification_by_loan(loan_id):
    return BalanceConsolidationVerification.objects.filter(
        loan_id=loan_id,
        validation_status=BalanceConsolidationStatus.DISBURSED
    ).last()


def check_and_update_loan_balance_consolidation(loan, transaction_method_id):
    consolidation_verification = get_or_none_balance_consolidation(loan.customer_id)
    if consolidation_verification:
        balance_consolidation = consolidation_verification.balance_consolidation
        check_account_destination = BankAccountDestination.objects.filter(
            pk=loan.bank_account_destination_id,
            name_bank_validation_id=consolidation_verification.name_bank_validation_id,
        ).exists()
        logger.info(
            {
                'action': 'check_and_update_loan_balance_consolidation',
                'loan': loan.__dict__,
                'balance_consolidation': balance_consolidation.pk,
            }
        )
        if (
            check_account_destination
            and int(transaction_method_id) == TransactionMethodCode.BALANCE_CONSOLIDATION.code
            and balance_consolidation.loan_outstanding_amount == loan.loan_disbursement_amount
        ):
            consolidation_verification.loan = loan
            consolidation_verification.save()
        else:
            raise BalanceConsolidationNotMatchException(
                BalanceConsolidationMessageException.DATA_NOT_MATCH
            )
        return True
    return False


class BalanceConsolidationToken:
    def __init__(self):
        self.fernet = Fernet(settings.BALANCE_CONS_SUBMIT_FORM_SECRET_KEY)

    def generate_token_balance_cons_submit(self, customer_id):
        balance_cons_fs = FeatureSetting.objects.filter(
            feature_name=BalanceConsolidationFeatureName.BALANCE_CONS_TOKEN_CONFIG, is_active=True
        ).last()
        if balance_cons_fs:
            expiry_duration = balance_cons_fs.parameters.get(
                'token_expiry_days', TOKEN_EXPIRATION_DAYS
            )
        else:
            expiry_duration = TOKEN_EXPIRATION_DAYS

        event_time = timezone.localtime(timezone.now())
        expiry_time = event_time + timedelta(days=expiry_duration)

        info_dict = {
            'customer_id': customer_id,
            'event_time': event_time.timestamp(),
            'expiry_time': expiry_time.timestamp(),
        }
        encrypted_info = json.dumps(info_dict)
        encrypted_key = self.fernet.encrypt(encrypted_info.encode()).decode()

        logger.info(
            {
                'action': 'generate_token_balance_cons_submit_action',
                **info_dict,
                'encrypted_key': encrypted_key,
            }
        )
        return event_time, expiry_time, encrypted_key

    def decrypt_token_balance_cons_submit(self, token):
        decrypted_info = self.fernet.decrypt(token.encode()).decode()
        info_dict = json.loads(decrypted_info)
        now = timezone.localtime(timezone.now()).timestamp()
        if len(info_dict) != ELEMENTS_IN_TOKEN or now > info_dict['expiry_time']:
            raise InvalidToken

        return info_dict['customer_id'], info_dict['expiry_time']


def filter_app_statuses_crm(from_status):
    allow_moving_statuses = BalanceConsolidationStatus.get_allow_moving_status()
    available_statuses = allow_moving_statuses.get(from_status, set())
    return [[status, status] for status in available_statuses]


def get_lock_status(obj, is_lock_by_me):
    # logic lock in here
    lock_status = 1
    if not obj.is_locked or is_lock_by_me:
        lock_status = 0
    return lock_status


def get_lock_edit(obj):
    lock_edit = 1
    if obj.validation_status == BalanceConsolidationStatus.ON_REVIEW:
        lock_edit = 0
    return lock_edit


def get_status_map_change_reason():
    fs = FeatureSetting.objects.filter(
        feature_name=BalanceConsolidationFeatureName.BALANCE_CONS_CRM_CONFIG, is_active=True
    ).last()
    if not fs:
        return {}
    parameters = fs.parameters or {}
    return json.dumps(parameters.get('status_map_change_reason', {}))


def update_balance_consolidation_data(balance_consolidation, agent, data):
    historical_data = []
    with transaction.atomic():
        for field_name, new_value in data.items():
            if field_name == 'fintech':
                new_value = Fintech.objects.get(pk=int(new_value))
            elif field_name in ('loan_principal_amount', 'loan_outstanding_amount'):
                new_value = int(new_value)
            elif field_name in ('disbursement_date', 'due_date'):
                new_value = datetime.strptime(new_value, '%Y-%m-%d').date()

            old_value = getattr(balance_consolidation, field_name)

            if new_value == old_value:
                continue

            setattr(balance_consolidation, field_name, new_value)

            historical_data.append(
                BalanceConsolidationHistory(
                    balance_consolidation=balance_consolidation,
                    agent=agent,
                    field_name=field_name,
                    old_value=old_value,
                    new_value=new_value,
                )
            )
        balance_consolidation.save()
        BalanceConsolidationHistory.objects.bulk_create(historical_data)
    return True


def get_balance_consolidation_detail_list_history(balance_conlidation):
    fintechs = Fintech.objects.all()
    fintech_dict = {i.id: i.name for i in fintechs}

    balance_consolidation_history = (
        balance_conlidation.balanceconsolidationhistory_set.select_related('agent')
        .values('field_name', 'old_value', 'new_value', 'cdate', 'agent__user_extension')
        .order_by('-cdate')
    )
    result = []
    for change in balance_consolidation_history:
        old_value = change['old_value']
        new_value = change['new_value']
        if change['field_name'] == 'fintech':
            old_value = fintech_dict.get(int(old_value))
            new_value = fintech_dict.get(int(new_value))
        result.append(
            {
                "field_name": change['field_name'],
                "old_value": old_value,
                "new_value": new_value,
                "cdate": change['cdate'],
                "agent": change['agent__user_extension'],
            }
        )
    return result


def get_status_note_histories(balance_consolidation_verification):
    return balance_consolidation_verification.balanceconsolidationverificationhistory_set.filter(
        field_name__in=['validation_status', 'note']
    ).order_by('-cdate')


def process_balance_consolidation_upload_signature_image(image, customer_id, thumbnail=True):
    # Upload file to oss
    image_path = image.image.path
    # Create remote filepath
    folder_type = 'balance_consolidation_'
    image_remote_filepath = construct_customize_remote_filepath(customer_id, image, folder_type)
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, image.image.path, image_remote_filepath)
    image.update_safely(url=image_remote_filepath)
    logger.info(
        {
            'status': 'successfull balance consolidation upload image to s3',
            'image_remote_filepath': image_remote_filepath,
            'balance_consolidation_id': image.image_source,
            'image_type': image.image_type,
        }
    )

    if image.image_ext != '.pdf' and thumbnail:

        # create thumbnail
        im = Imagealias.open(image.image.path)
        im = im.convert('RGB')
        size = (150, 150)
        im.thumbnail(size, Imagealias.ANTIALIAS)
        image_thumbnail_path = image.thumbnail_path
        im.save(image_thumbnail_path)

        # upload thumbnail to s3
        thumbnail_dest_name = construct_customize_remote_filepath(
            customer_id, image, folder_type, suffix='thumbnail'
        )
        upload_file_to_oss(settings.OSS_MEDIA_BUCKET, image_thumbnail_path, thumbnail_dest_name)
        image.update_safely(thumbnail_url=thumbnail_dest_name)

        logger.info(
            {
                'status': 'successfull upload thumbnail to s3',
                'thumbnail_dest_name': thumbnail_dest_name,
                'application_id': image.image_source,
                'image_type': image.image_type,
            }
        )

        # delete thumbnail from local disk
        if os.path.isfile(image_thumbnail_path):
            logger.info(
                {
                    'action': 'deleting_thumbnail_local_file',
                    'image_thumbnail_path': image_thumbnail_path,
                    'application_id': image.image_source,
                    'image_type': image.image_type,
                }
            )
            os.remove(image_thumbnail_path)

    # Delete a local file image
    if os.path.isfile(image_path):
        logger.info(
            {
                'action': 'deleting_local_file',
                'image_path': image_path,
                'loan_id': image.image_source,
                'image_type': image.image_type,
            }
        )
        image.image.delete()

    if image.image_status != Image.CURRENT:
        return

    # mark all other images with same type as 'deleted'
    images = list(
        Image.objects.exclude(id=image.id)
        .exclude(image_status=Image.DELETED)
        .filter(image_source=image.image_source, image_type=image.image_type)
    )
    for img in images:
        logger.info({'action': 'marking_deleted', 'image': img.id})
        img.update_safely(image_status=Image.DELETED)


def get_skrtp_template_temporary_loan(balance_consolidation):
    account = balance_consolidation.customer.account
    application = balance_consolidation.customer.account.get_active_application()

    account_limit = account.get_account_limit
    if not account_limit or not application:
        return

    loan_duration = balance_consolidation.loan_duration
    principal_rest, _, installment_rest = compute_payment_installment_julo_one(
        balance_consolidation.loan_outstanding_amount, loan_duration, 0
    )

    payments = []
    for payment_number in range(loan_duration):
        # Calculate payment every months
        payments.append(
            Payment(
                payment_number=payment_number + 1,
                due_amount=display_rupiah_skrtp(installment_rest),
                installment_principal=display_rupiah_skrtp(principal_rest),
                installment_interest=0,
            )
        )

    loan_type = 'pinjaman kirim dana'
    julo_bank_code = '-'
    payment_method_name = '-'
    payment_method = PaymentMethod.objects.filter(
        virtual_account=application.bank_account_number
    ).first()
    if payment_method:
        julo_bank_code = payment_method.bank_code
        payment_method_name = payment_method.payment_method_name

    context = {
        'balance_consolidation': balance_consolidation,
        'application': application,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'full_address': application.full_address,
        'payments': payments,
        'date_today': format_date(
            timezone.localtime(timezone.now()).date(), 'd MMMM yyyy', locale='id_ID'
        ),
        'interest_fee_monthly': display_rupiah_skrtp(0),
        'julo_bank_name': application.bank_name,
        'julo_bank_code': julo_bank_code,
        'payment_method_name': payment_method_name,
        'julo_bank_account_number': application.bank_account_number,
        'loan_type': loan_type,
        'available_limit': display_rupiah_skrtp(account_limit.available_limit),
    }

    template = render_to_string(
        '../../julo/templates/loan_agreement/temporary_skrtp.html', context=context
    )

    return template


def get_loan_balance_consolidation_duration(application, customer, loan_amount):
    transaction_method = TransactionMethodCode.BALANCE_CONSOLIDATION
    _, credit_matrix_product_line = get_credit_matrix_and_credit_matrix_product_line(
        application=application, transaction_type=transaction_method.name
    )

    account_limit = AccountLimit.objects.filter(account=application.account).last()
    set_limit = account_limit.set_limit

    credit_matrix_repeat = get_credit_matrix_repeat(
        customer.id,
        credit_matrix_product_line.product.product_line_code,
        transaction_method.code,
    )
    max_duration = credit_matrix_product_line.max_duration
    min_duration = credit_matrix_product_line.min_duration
    if credit_matrix_repeat:
        max_duration = credit_matrix_repeat.max_tenure
        min_duration = credit_matrix_repeat.min_tenure

    available_durations = get_loan_duration(
        loan_amount,
        max_duration,
        min_duration,
        set_limit,
        customer,
        application,
    )
    # filter out duration less than 60 days due to google restriction for cash loan
    available_durations = refiltering_cash_loan_duration(available_durations, application)
    return available_durations


def get_transaction_detail_balance_consolidation(balance_consolidation, transaction_method):
    fintech_name = balance_consolidation.fintech.name
    bank_account_number = balance_consolidation.bank_account_number
    transaction_details = [
        'Transaction method: {}'.format(transaction_method.fe_display_name),
        'Fintech: {}'.format(fintech_name),
        'Bank name: {}'.format(balance_consolidation.bank_name),
        'Bank account no: {}'.format(bank_account_number)
    ]
    transaction_detail = ',<br>'.join(transaction_details)
    return transaction_detail


def get_limit_incentive_config():
    data = {}
    fs = FeatureSetting.objects.filter(
        feature_name=BalconLimitIncentiveConst.LIMIT_INCENTIVE_FS_NAME,
        is_active=True
    ).last()

    if fs:
        data = fs.parameters

    return data


def get_downgrade_amount_balcon_punishments(available_limit, bonus_incentive):
    if available_limit <= 0:
        return 0  # No downgrade
    return min(available_limit, bonus_incentive)


def update_balcon_verification_after_punishments(balcon_verification, deduction_amount):
    account_limit_histories = balcon_verification.account_limit_histories
    account_limit_histories['punishments'] = {
        "deduct_bonus_incentive": deduction_amount
    }
    balcon_verification.account_limit_histories = account_limit_histories
    balcon_verification.save()


def apply_downgrade_limit_for_balcon_punishments(customer_id, balcon_verification):
    """
        Apply downgrade limit for BalCon punishments, include:
            - Get bonus incentive that customer get when creating BalCon loan
            - Trigger downgrade
    """
    account = Account.objects.get(customer_id=customer_id)
    account_limit = AccountLimit.objects.get(account_id=account.pk)
    bonus_incentive = balcon_verification.account_limit_histories['upgrade']['bonus_incentive']

    # Get deduction amount from account limit histories in balcon verification
    deduction_amount = get_downgrade_amount_balcon_punishments(account_limit.available_limit, bonus_incentive)
    if deduction_amount == 0:
        logger.info(
            {
                'action': 'apply_downgrade_limit_for_balcon_punishments',
                'message': 'No deduction amount, downgrade skipped',
                'customer_id': customer_id,
                'balcon_verification_id': balcon_verification.id,
            }
        )
        return 0

    return process_downgrade_limit_for_balcon_punishments(
        balcon_verification=balcon_verification,
        account_limit=account_limit,
        deduction_amount=deduction_amount
    )


def process_downgrade_limit_for_balcon_punishments(balcon_verification, account_limit, deduction_amount):
    new_set_limit = account_limit.set_limit - deduction_amount
    new_max_limit = account_limit.max_limit - deduction_amount
    graduation_flow = DowngradeType.BALCON_PUNISHMENTS
    with transaction.atomic():
        run_downgrade_limit(
            account_limit.account_id,
            new_set_limit,
            new_max_limit,
            graduation_flow,
        )
        update_balcon_verification_after_punishments(balcon_verification, deduction_amount)
    logger.info(
        {
            'action': 'process_downgrade_limit_for_balcon_punishments',
            'message': 'Run downgrade limit for BalCon punishment',
            'customer_id': account_limit.account.customer_id,
            'deduction_amount': deduction_amount,
            'new_set_limit': new_set_limit,
            'new_max_limit': new_max_limit
        }
    )
    return deduction_amount


def get_and_validate_fdc_data_for_balcon_punishments(verification_id, customer_id):
    balcon_verification = BalanceConsolidationVerification.objects.filter(
        pk=verification_id
    ).last()

    if not balcon_verification:
        logger.info({
            'action': 'get_and_validate_fdc_data_for_balcon_punishments',
            'message': 'Balance Consolidation Verification not found',
            'data': {
                'customer_id': customer_id,
                'verification_id': verification_id
            }
        })
        return

    fdc_inquiry_data = get_and_save_customer_latest_fdc_data(customer_id)
    invalid_fdc_inquiry_loan = get_invalid_loan_from_other_fintech(
        fdc_inquiry_data=fdc_inquiry_data,
        balcon_verification=balcon_verification
    )

    if invalid_fdc_inquiry_loan:
        # Create record to track the BalCon FDC checking
        BalanceConsolidationDelinquentFDCChecking.objects.create(
            customer_id=customer_id,
            balance_consolidation_verification=balcon_verification,
            invalid_fdc_inquiry_loan_id=invalid_fdc_inquiry_loan.id,
            is_punishment_triggered=False
        )

        # Trigger BalCon punishments
        trigger_balcon_punishments(customer_id, balcon_verification)


def get_delay_fdc_data_hour_from_fs():
    """
        Feature setting to determine how outdated data from FDC can be used
    """
    delay_fdc_data_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FETCH_FDC_DATA_DELAY,
        is_active=True
    ).last()

    return delay_fdc_data_fs and delay_fdc_data_fs.parameters.get('delay_hour', 0)


def get_and_save_customer_latest_fdc_data(customer_id):
    customer = Customer.objects.get(pk=customer_id)
    nik = customer.nik

    delay_hour = get_delay_fdc_data_hour_from_fs()
    last_fdc_inquiry = FDCInquiry.objects.filter(
        nik=customer.nik,
        inquiry_status='success',
        status__iexact=FDCStatus.FOUND
    ).last()
    now = timezone.localtime(timezone.now())
    if (
        delay_hour
        and last_fdc_inquiry
        and last_fdc_inquiry.cdate + timedelta(hours=delay_hour) >= now
    ):
        fdc_inquiry_data = {'id': last_fdc_inquiry.id, 'nik': nik}

        logger.info({
            'action': 'get_and_save_customer_latest_fdc_data',
            'message': 'Get customer FDC data from DB',
            'customer_id': customer_id
        })
    else:
        fdc_inquiry = FDCInquiry.objects.create(nik=nik, customer_id=customer.id)
        fdc_inquiry_data = {'id': fdc_inquiry.id, 'nik': nik}
        get_and_save_fdc_data(
            fdc_inquiry_data=fdc_inquiry_data,
            reason=FDCReasonConst.REASON_MONITOR_OUTSTANDING_BORROWER,
            retry=False
        )

        logger.info({
            'action': 'get_and_save_customer_latest_fdc_data',
            'message': 'Get customer FDC data hit API',
            'customer_id': customer_id
        })

    return fdc_inquiry_data


def get_invalid_loan_from_other_fintech(fdc_inquiry_data, balcon_verification):
    balance_consolidation = balcon_verification.balance_consolidation
    invalid_fdc_inquiry_loan = FDCInquiryLoan.objects.filter(
        fdc_inquiry_id=fdc_inquiry_data['id'],
        status_pinjaman='Outstanding',
        id_penyelenggara=balance_consolidation.fintech_id,
        tgl_penyaluran_dana__gt=balance_consolidation.cdate.date()
    ).exclude(
        is_julo_loan=True
    ).last()

    logger.info({
        'action': 'get_invalid_loan_from_other_fintech',
        'message': 'Get customer invalid loan from other fintech',
        'fdc_inquiry_data': fdc_inquiry_data
    })

    return invalid_fdc_inquiry_loan


def trigger_balcon_punishments(customer_id, balcon_verification):
    """
        Trigger Balance consolidation punishments for delinquent customers through FDC checking, include:
            - Downgrade limit
            - Remove 0% interest from Balance Consolidation loan
    """
    # Check if the punishment process was triggered to the customer or not
    balcon_delinquent_checking = BalanceConsolidationDelinquentFDCChecking.objects.filter(
        customer_id=customer_id, balance_consolidation_verification=balcon_verification
    ).last()

    if balcon_delinquent_checking and not balcon_delinquent_checking.is_punishment_triggered:
        # Trigger Balance Consolidation punishments
        limit_deducted = apply_downgrade_limit_for_balcon_punishments(
            customer_id=customer_id,
            balcon_verification=balcon_verification
        )

        # Trigger punishment functions here
        reverse_all_payment_paid_interest(customer_id, balcon_verification)

        # Update BalCon delinquent checking
        balcon_delinquent_checking.update_safely(is_punishment_triggered=True)

        # Send event to MoEngage
        fintech_id = balcon_verification.balance_consolidation.fintech_id
        fintech = Fintech.objects.filter(pk=fintech_id, is_active=True).last()

        if not fintech:
            logger.info({
                'action': 'trigger_balcon_punishments',
                'message': 'Fintech not found',
                'fintech_id': fintech_id
            })
            return

        send_event_moengage_for_balcon_punishment.delay(
            customer_id=customer_id,
            limit_deducted=limit_deducted,
            fintech_id=fintech_id,
            fintech_name=fintech.name
        )

        # Log for tracking
        logger.info({
            'action': 'trigger_balcon_punishments',
            'message': 'Finish Balance consolidation punishment',
            'customer_id': customer_id
        })


def reverse_all_payment_paid_interest(
    customer_id: int, balcon_verification: BalanceConsolidationVerification
):
    """
    Reverse all payment paid interest (only for paymnent_status < 330) for delinquent customer
    """
    account = Account.objects.filter(customer_id=customer_id).last()
    payment_event_ids = balcon_verification.extra_data['payment_event_ids']
    account_transaction = None
    transaction_type = 'payment_void'
    local_trx_time = timezone.localtime(timezone.now())
    towards_interest = 0
    voided_events = []

    with transaction.atomic():
        for payment_event_id in payment_event_ids:
            payment_event = PaymentEvent.objects.get(pk=payment_event_id)
            account_transaction = payment_event.account_transaction

            # lock payment and account_payment data
            payment = Payment.objects.select_for_update().filter(
                pk=payment_event.payment_id, payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
            ).last()
            if not payment:
                continue

            account_payment = AccountPayment.objects.select_for_update().get(
                pk=payment.account_payment_id
            )

            remaining_amount = payment_event.event_payment
            total_reversed_interest = 0
            if remaining_amount > 0:
                remaining_amount, total_reversed_interest = consume_reversal_for_interest(
                    [payment], remaining_amount, account_payment
                )

            if total_reversed_interest <= 0:
                continue

            payment_event_void = store_reversed_payment_balcon_delinquent(
                payment=payment,
                reversed_date=payment_event.event_date,
                total_reversed_amount=total_reversed_interest,
                note='Reversal interest due to balcon delinquency',
            )

            account_payment_updated_fields = [
                'due_amount',
                'paid_amount',
                'paid_interest',
                'status',
                'udate',
            ]
            account_payment.save(update_fields=account_payment_updated_fields)

            towards_interest += total_reversed_interest
            voided_events.append(payment_event_void)

        reversal_account_trx = AccountTransaction.objects.create(
            account=account,
            transaction_date=local_trx_time,
            transaction_amount=-towards_interest,
            transaction_type=transaction_type,
            towards_principal=0,
            towards_interest=-towards_interest,
            towards_latefee=0,
            can_reverse=False,
            accounting_date=local_trx_time.date()
        )
        for payment_event_void in voided_events:
            payment_event_void.update_safely(account_transaction=reversal_account_trx)

        account_transaction.update_safely(
            can_reverse=False, reversal_transaction=reversal_account_trx
        )


def store_reversed_payment_balcon_delinquent(
    payment,
    reversed_date,
    total_reversed_amount,
    note=''
):
    payment_event = PaymentEvent.objects.create(
        payment=payment,
        event_payment=-total_reversed_amount,
        event_due_amount=payment.due_amount - total_reversed_amount,
        event_date=reversed_date,
        event_type=PaymentEventConst.PAYMENT_VOID,
        can_reverse=False,  # reverse (void) must be via account payment level
    )

    payment_update_fields = [
        'paid_interest',
        'paid_amount',
        'due_amount',
        'payment_status',
        'udate',
    ]
    payment.save(update_fields=payment_update_fields)

    reversal_type = 'Payment'
    note = ',\nnote: %s' % note
    note_payment_method = ',\n'
    template_note = (
        '[Reversal %s]\n\
    amount: %s,\n\
    date: %s%s%s.'
        % (
            reversal_type,
            display_rupiah(payment_event.event_payment),
            payment_event.event_date.strftime("%d-%m-%Y"),
            note_payment_method,
            note,
        )
    )

    PaymentNote.objects.create(note_text=template_note, payment=payment)

    return payment_event
