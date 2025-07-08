import json
import logging
import re
from builtins import object
from datetime import timedelta
from typing import List, Tuple, Union, Optional
from urllib.parse import urlparse

from cuser.middleware import CuserMiddleware
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.template.loader import get_template
from django.utils import timezone
from django.utils.text import slugify

from juloserver.account.constants import AccountConstant
from juloserver.account.models import Address
from juloserver.application_form.serializers.application_serializer import (
    ApplicationValidator,
)
from juloserver.customer_module.constants import (
    AccountDeletionRequestStatuses,
    AccountDeletionStatusChangeReasons,
    CashbackBalanceStatusConstant,
    ChangeCustomerPrimaryPhoneMessages,
    ChangePhoneLostAccess,
    ConsentWithdrawal,
    CustomerDataChangeRequestConst,
    FailedAccountDeletionRequestStatuses,
    forbidden_account_status_account_deletion,
    forbidden_application_status_account_deletion,
    forbidden_loan_status_account_deletion,
    ongoing_account_deletion_request_statuses,
)
from juloserver.customer_module.exceptions import CustomerApiException
from juloserver.customer_module.models import (
    AccountDeletionRequest,
    CashbackBalance,
    CashbackStatusHistory,
    ConsentWithdrawalRequest,
    CustomerDataChangeRequest,
    CustomerProductLocked,
    CXDocument,
)
from juloserver.customer_module.services.account_deletion import (
    is_complete_deletion,
    process_revert_applications_status_deletion,
)
from juloserver.customer_module.services.device_related import get_device_repository
from juloserver.customer_module.services.digital_signature import Signature
from juloserver.customer_module.services.email import (
    generate_image_attachment,
    send_email_with_html,
)
from juloserver.customer_module.tasks.account_deletion_tasks import (
    send_cancel_deletion_request_success_email,
    send_create_deletion_request_success_email,
)
from juloserver.customer_module.tasks.customer_related_tasks import (
    send_consent_withdraw_email,
)
from juloserver.customer_module.tasks.master_agreement_tasks import (
    generate_application_master_agreement,
)
from juloserver.customer_module.tasks.notification import (
    send_reset_phone_number_email_task,
)
from juloserver.customer_module.utils.utils_crm_v1 import get_active_loan_ids
from juloserver.julo.clients import (
    get_julo_pn_client,
    get_julo_sentry_client,
)
from juloserver.julo.constants import FeatureNameConst, MobileFeatureNameConst
from juloserver.julo.exceptions import JuloInvalidStatusChange
from juloserver.julo.models import (
    Application,
    ApplicationFieldChange,
    AuthUser,
    AuthUserFieldChange,
    Customer,
    CustomerFieldChange,
    Image,
    Loan,
    MasterAgreementTemplate,
    MobileFeatureSetting,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import (
    delete_public_file_from_oss,
    generate_phone_number_key,
    seconds_until_end_of_day,
)
from juloserver.payback.constants import GopayAccountErrorConst
from juloserver.pii_vault.constants import PiiSource, PIIType
from juloserver.pii_vault.services import (
    detokenize_for_model_object,
    detokenize_value_lookup,
)
from juloserver.pin.utils import get_first_name
from juloserver.streamlined_communication.constant import PageType
from juloserver.streamlined_communication.services2.email_services import (
    get_email_service,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class CustomerService(object):
    @transaction.atomic
    def change_email(self, user, new_email):
        user = AuthUser.objects.get(pk=user.id)
        customer = Customer.objects.get(user=user)
        detokenize_customers = detokenize_for_model_object(
            PiiSource.CUSTOMER,
            [
                {
                    'object': customer,
                }
            ],
            force_get_local_data=True,
        )
        customer = detokenize_customers[0]
        old_email = customer.email

        if old_email == new_email:
            raise CustomerApiException(
                "You have entered the same email as yours "
                "right now, please give different email."
            )

        # detokenize query here
        # TODO, make another query with detokenized value in the future
        detokenize_value_lookup(new_email, PIIType.CUSTOMER)
        customer_with_existing_email = Customer.objects.filter(email=new_email).last()
        application_with_existing_email = Application.objects.filter(email=new_email).last()

        if customer_with_existing_email is None and application_with_existing_email is None:
            application = Application.objects.filter(customer=customer).latest('id')
            if application:
                detokenize_applications = detokenize_for_model_object(
                    PiiSource.APPLICATION,
                    [
                        {
                            'customer_xid': application.customer.customer_xid,
                            'object': application,
                        }
                    ],
                    force_get_local_data=True,
                )
                application = detokenize_applications[0]
            if application.product_line_code == ProductLineCodes.JULOVER:
                raise CustomerApiException("Anda tidak dapat mengubah email Anda")
            with transaction.atomic():
                customer.update_safely(email=new_email)
                user.email = new_email
                user.save()
                ApplicationFieldChange.objects.create(
                    field_name='email',
                    old_value=application.email,
                    new_value=new_email,
                    application=application,
                )

                if application:
                    application.update_safely(email=new_email)

                current_user = CuserMiddleware.get_user()
                if not current_user:
                    CuserMiddleware.set_user(user)

                CustomerFieldChange.objects.create(
                    customer=customer,
                    field_name='email',
                    old_value=old_email,
                    new_value=new_email,
                    application=application,
                )
        else:
            raise CustomerApiException("Email has already registered.")


class PpfpBorrowerSignature(Signature):
    """Signature for PPFP Document that intended to borrower.
    PPFP stands for Perjanjian Pemberian Fasilitas Pendanaan
    """

    @property
    def reason(self) -> str:
        return "Setuju untuk meminjam"

    @property
    def box(self) -> tuple:
        v_start = 390
        h_start = 580
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 7


class PpfpProviderSignature(Signature):
    """Signature for PPFP Document that intended to provider (Julo).
    PPFP stands for Perjanjian Pemberian Fasilitas Pendanaan
    """

    @property
    def reason(self) -> str:
        return "Setuju untuk memberikan dana"

    @property
    def box(self) -> tuple:
        v_start = 35
        h_start = 580
        return v_start, h_start, v_start + self.width, h_start + self.height

    @property
    def page(self) -> int:
        return 7


def get_customer_status(customer: Customer) -> (bool, bool):
    """
    Decide that customer should be forced to create new PIN
    and also decide that customer should use new UI
    """
    use_new_ui = False
    show_setup_pin = False

    application = customer.application_set.last()

    if customer.can_reapply or not application or application.can_access_julo_app():
        use_new_ui = True
        if not hasattr(customer.user, 'pin'):
            show_setup_pin = True

    return use_new_ui, show_setup_pin


def update_cashback_balance_status(customer, is_dpd_90=False):
    with transaction.atomic():
        cashback_balance = CashbackBalance.objects.filter(customer=customer).last()
        if not cashback_balance:
            return
        is_cashback_freeze = customer.is_cashback_freeze
        status_old = cashback_balance.status
        status_new = CashbackBalanceStatusConstant.FREEZE
        if not is_cashback_freeze or is_dpd_90:
            status_new = CashbackBalanceStatusConstant.UNFREEZE
        if cashback_balance.status != status_new:
            cashback_balance.update_safely(status=status_new)
            CashbackStatusHistory.objects.create(
                status_old=status_old,
                status_new=status_new,
                cashback_balance=cashback_balance,
            )


def change_customer_primary_phone_number(application, new_phone_number, with_reset_key=False):
    try:
        customer = application.customer
        detokenize_customers = detokenize_for_model_object(
            PiiSource.CUSTOMER,
            [
                {
                    'object': customer,
                }
            ],
            force_get_local_data=True,
        )
        customer = detokenize_customers[0]
        detokenize_applications = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [
                {
                    'customer_xid': application.customer.customer_xid,
                    'object': application,
                }
            ],
            force_get_local_data=True,
        )
        application = detokenize_applications[0]
        with transaction.atomic():
            old_phone_number = application.mobile_phone_1
            application.mobile_phone_1 = new_phone_number
            application.save()

            customer.phone = new_phone_number
            if with_reset_key:
                customer.reset_password_key = None
                customer.reset_password_exp_date = None
            customer.save()

            user = customer.user
            if re.fullmatch(ApplicationValidator._normal_phone_regex, user.username):
                old_username = user.username
                user.username = customer.nik
                user.save(update_fields=['username'])
                AuthUserFieldChange.objects.create(
                    user=user,
                    customer=customer,
                    field_name='username',
                    old_value=old_username,
                    new_value=user.username,
                )

            ApplicationFieldChange.objects.create(
                application=application,
                field_name='mobile_phone_1',
                old_value=old_phone_number,
                new_value=application.mobile_phone_1,
            )
            CustomerFieldChange.objects.create(
                customer=customer,
                field_name='phone',
                old_value=old_phone_number,
                new_value=customer.phone,
                application=application,
            )

            return True, ChangeCustomerPrimaryPhoneMessages.SUCCESS, None
    except Exception as e:
        return False, None, str(e)


def get_or_create_cashback_balance(customer):
    cashback_balance = CashbackBalance.objects.filter(customer=customer).last()
    if not cashback_balance:
        with transaction.atomic():
            cashback_balance = CashbackBalance.objects.create(
                customer=customer, status=CashbackBalanceStatusConstant.UNFREEZE
            )
            CashbackStatusHistory.objects.create(
                cashback_balance=cashback_balance, status_new=cashback_balance.status
            )
    return cashback_balance


def master_agreement_template(application, show_signature=True):
    ma_template = MasterAgreementTemplate.objects.filter(product_name='J1', is_active=True).last()

    if not ma_template:
        logger.error(
            {
                'action_view': 'Master Agreement - get_master_agreement_template',
                'data': {},
                'errors': 'Master Agreement Template tidak ditemukan',
            }
        )
        return False

    if len(ma_template.parameters) == 0:
        logger.error(
            {
                'action_view': 'Master Agreement - get_master_agreement_template',
                'data': {},
                'errors': 'Body content tidak ada',
            }
        )
        return False

    return master_agreement_content(application, ma_template.parameters, show_signature)


def master_agreement_content(application, template, show_signature=True, new_signature=False):
    import datetime

    from babel.dates import format_datetime
    from babel.numbers import format_number

    from juloserver.loan_refinancing.templatetags.format_date import (
        format_date_to_locale_format,
    )

    customer = application.customer
    if not customer:
        logger.error(
            {
                'action_view': 'Master Agreement - master_agreement_content',
                'data': {},
                'errors': 'Customer tidak ditemukan',
            }
        )
        return False

    account = customer.account
    if not account:
        logger.error(
            {
                'action_view': 'Master Agreement - master_agreement_content',
                'data': {},
                'errors': 'Customer tidak ditemukan',
            }
        )
        return False

    first_credit_limit = account.accountlimit_set.first().set_limit
    if not first_credit_limit:
        logger.error(
            {
                'action_view': 'Master Agreement - master_agreement_content',
                'data': {},
                'errors': 'First Credit Limit tidak ditemukan',
            }
        )
        return False

    customer_name = customer.fullname
    today = datetime.datetime.now()
    hash_digi_sign = "PPFP-" + str(application.application_xid)
    dob = format_date_to_locale_format(application.dob)
    signature = ""

    if show_signature:
        signature = (
            '<table border="0" cellpadding="1" cellspacing="1" style="border:none;">'
            '<tbody><tr><td><p><strong>PT. JULO Teknologi Finansial</strong><br>'
            '(dalam kedudukan selaku kuasa Pemberi Dana)<br>'
            '<cite><tt>Adrianus Hitijahubessy</tt></cite></span></p>'
            'Jabatan: Direktur</p></td>'
            '<td><p style="text-align:right">'
            'Jakarta, ' + format_date_to_locale_format(today) + '</p>'
            '<p style="text-align:right">Penerima&nbsp;Dana,</p>'
            '<p style="text-align:right"><span style="font-family:Allura">'
            '<cite><tt>' + customer_name + '</tt></cite></span></p>'
            '<p style="text-align:right">' + customer_name + '</p></td>'
            '</tr></tbody></table>'
        )

    if new_signature:
        signature = (
            '<table border="0" cellpadding="1" cellspacing="1" style="border:none;">'
            '<tbody><tr><td><p><strong>PT. JULO Teknologi Finansial</strong><br>'
            'Kuasa dari Pemberi Dana<br>'
            '<cite><tt>Gharnis Athe M. Ginting</tt></cite></span></p>'
            'Kuasa Direktur</p></td>'
            '<td><p style="text-align:right">'
            'Jakarta, ' + format_date_to_locale_format(today) + '</p>'
            '<p style="text-align:right">Penerima&nbsp;Dana,</p>'
            '<p style="text-align:right"><span style="font-family:Allura">'
            '<cite><tt>' + customer_name + '</tt></cite></span></p>'
            '<p style="text-align:right">' + customer_name + '</p></td>'
            '</tr></tbody></table>'
        )

    ma_content = template.format(
        hash_digi_sign=hash_digi_sign,
        date_today=format_datetime(today, 'd MMMM yyyy, HH:mm:ss', locale='id_ID'),
        customer_name=customer_name,
        dob=dob,
        customer_nik=application.ktp,
        customer_phone=application.mobile_phone_1,
        customer_email=application.email,
        full_address=application.full_address,
        first_credit_limit=format_number(first_credit_limit, locale='id_ID'),
        link_history_transaction=settings.BASE_URL + "/account/v1/account/account_payment",
        tnc_link="https://www.julo.co.id/privacy-policy",
        signature=signature,
    )

    return ma_content


def master_agreement_pdf(application, template, new_signature):
    import datetime

    from django.template.loader import render_to_string

    from juloserver.julo.exceptions import JuloException
    from juloserver.loan_refinancing.templatetags.format_date import (
        format_date_to_locale_format,
    )

    body = master_agreement_content(application, template, False)
    if not body:
        raise JuloException("Could not render body for incomplete data.")

    customer_name = application.customer.fullname.title()
    today = datetime.datetime.now()

    if not new_signature:
        signature = (
            '<table border="0" cellpadding="1" cellspacing="1" style="border:none; width:100%;">'
            '<tbody><tr><td><p><strong>PT. JULO Teknologi Finansial</strong><br>'
            '(dalam kedudukan selaku kuasa Pemberi Dana)<br>'
            '<div class="signature-font">Adrianus Hitijahubessy</div>'
            '<p>Jabatan: Direktur</p></td>'
            '<td><p style="text-align:right">'
            'Jakarta, ' + format_date_to_locale_format(today) + '</p>'
            '<p style="text-align:right">Penerima&nbsp;Dana,</p>'
            '<div style="text-align:right" class="signature-font">' + customer_name + '</div>'
            '<p style="text-align:right">' + customer_name + '</p></td>'
            '</tr></tbody></table>'
        )
    else:
        signature = (
            '<table border="0" cellpadding="1" cellspacing="1" style="border:none; width:100%;">'
            '<tbody><tr><td><p><strong>PT. JULO Teknologi Finansial</strong><br>'
            'Kuasa dari Pemberi Dana<br>'
            '<div class="signature-font">Gharnis Athe M. Ginting</div>'
            '<p>Kuasa Direktur</p></td>'
            '<td><p style="text-align:right">'
            'Jakarta, ' + format_date_to_locale_format(today) + '</p>'
            '<p style="text-align:right">Penerima&nbsp;Dana,</p>'
            '<div style="text-align:right" class="signature-font">' + customer_name + '</div>'
            '<p style="text-align:right">' + customer_name + '</p></td>'
            '</tr></tbody></table>'
        )

    context = {
        'body': body,
        'signature': signature,
    }

    return render_to_string('master_agreement_pdf.html', context=context)


def master_agreement_created(application_id, new_signature=False):
    if not application_id:
        return False

    generate_application_master_agreement.delay(application_id, new_signature)
    return True


def update_customer_data_by_application(customer, application, update_data):
    field_changes = []
    for field_name, new_value in update_data.items():
        current_value = getattr(customer, field_name)
        if current_value != new_value:
            field_changes.append(
                CustomerFieldChange(
                    customer=customer,
                    field_name=field_name,
                    old_value=current_value,
                    new_value=new_value,
                    application=application,
                )
            )
    with transaction.atomic():
        customer.update_safely(**update_data)
        CustomerFieldChange.objects.bulk_create(field_changes)
        if update_data.get('phone'):
            user = customer.user
            if re.fullmatch(ApplicationValidator._normal_phone_regex, user.username):
                old_username = user.username
                user.username = update_data['phone']
                user.save(update_fields=['username'])
                AuthUserFieldChange.objects.create(
                    user=user,
                    customer=customer,
                    field_name='username',
                    old_value=old_username,
                    new_value=user.username,
                )

    return customer


def julo_starter_proven_bypass(application):
    return application.is_julo_starter and (
        application.application_status_id == ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        or application.application_status_id == ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
    )


def unbind_customers_gopay_tokenization_account_linking(account):
    # Importing here due to import error
    from juloserver.payback.services.gopay import GopayServices

    gopay_services = GopayServices()
    response, error = gopay_services.unbind_gopay_account_linking(account)

    if response:
        if response == GopayAccountErrorConst.DEACTIVATED:
            return 'Gopay', None
        else:
            return 'Gopay Error', response
    elif error:
        if error == GopayAccountErrorConst.ACCOUNT_NOT_REGISTERED:
            return None, error
        else:
            return 'Gopay Error', error


def check_if_phone_exists(phone: str, customer: Customer) -> bool:
    """
    Check if a phone number exists in Application or Customer table.

    Parameters:
        phone (str): The phone number.
        customer (Customer): The customer.

    Returns:
        bool: True if the phone number exists in either the Application or Customer table,
              False otherwise.

    """
    if not phone:
        return False
    application = (
        Application.objects.filter(mobile_phone_1=phone).exclude(customer=customer).exists()
    )
    customer = Customer.objects.filter(phone=phone).exclude(pk=customer.pk).exists()

    if application or customer:
        return True

    return False


def get_customer_appsflyer_data(user):
    customer = Customer.objects.get_or_none(user=user)
    if not customer:
        return

    return {
        "appsflyer_device_id": customer.appsflyer_device_id,
        "appsflyer_customer_id": customer.appsflyer_customer_id,
        "advertising_id": customer.advertising_id,
    }


def set_customer_appsflyer_data(user, data):
    customer = Customer.objects.get_or_none(user=user)
    if not customer:
        return

    update_data = {}
    if (
        data.get('appsflyer_device_id')
        and data.get('appsflyer_device_id') != customer.appsflyer_device_id
    ):
        update_data['appsflyer_device_id'] = data.get('appsflyer_device_id')
    if (
        data.get('appsflyer_customer_id')
        and data.get('appsflyer_customer_id') != customer.appsflyer_customer_id
    ):
        update_data['appsflyer_customer_id'] = data.get('appsflyer_customer_id')
    if data.get('advertising_id') and data.get('advertising_id') != customer.advertising_id:
        update_data['advertising_id'] = data.get('advertising_id')

    if update_data:
        logger.info(
            'update_customer_appsflyer_info|customer={}, old_data={}, new_data={}'.format(
                customer.id,
                {
                    'appsflyer_device_id': customer.appsflyer_device_id,
                    'appsflyer_customer_id': customer.appsflyer_customer_id,
                    'advertising_id': customer.advertising_id,
                },
                update_data,
            )
        )
    customer.update_safely(**update_data)

    return {
        'appsflyer_device_id': customer.appsflyer_device_id,
        'appsflyer_customer_id': customer.appsflyer_customer_id,
        'advertising_id': customer.advertising_id,
    }


def is_user_delete_allowed(customer: Customer) -> Union[bool, str]:
    """
    Checks if customer is eligible for account deletion.
    Args:
        customer (Customer): Customer object to be checked.
    Returns:
        bool: True if eligible. False if not.
        str: Status returned when not eligible.
    """
    on_disbursement_loan = Loan.objects.filter(
        customer_id=customer.id,
        loan_status_id__in=forbidden_loan_status_account_deletion,
    )
    if on_disbursement_loan.exists():
        logger.warning(
            {
                'action': 'is_user_delete_allowed',
                'customer_id': customer.id,
                'on_disbursement_loan_ids': on_disbursement_loan.values_list('id', flat=True),
                'message': 'not allowed to delete, have on disbursement loan',
            }
        )
        return False, FailedAccountDeletionRequestStatuses.LOANS_ON_DISBURSEMENT

    active_loan_ids = get_active_loan_ids(customer)
    if active_loan_ids and len(active_loan_ids) > 0:
        logger.warning(
            {
                'action': 'is_user_delete_allowed',
                'customer_id': customer.id,
                'active_loan_ids': active_loan_ids,
                'message': 'not allowed to delete, have active loans',
            }
        )
        return False, FailedAccountDeletionRequestStatuses.ACTIVE_LOANS

    application = customer.application_set.last()
    if (
        application
        and application.application_status_id in forbidden_application_status_account_deletion
    ):
        logger.warning(
            {
                'action': 'is_user_delete_allowed',
                'customer_id': customer.id,
                'application_id': application.id,
                'application_status_id': application.application_status_id,
                'message': 'not allowed to delete, application status forbidden',
            }
        )
        return False, FailedAccountDeletionRequestStatuses.APPLICATION_NOT_ELIGIBLE

    account = customer.account_set.last()
    if account and account.status_id in forbidden_account_status_account_deletion:
        logger.warning(
            {
                'action': 'is_user_delete_allowed',
                'customer_id': customer.id,
                'account_id': account.id,
                'account_status_id': account.status_id,
                'message': 'not allowed to delete, account status forbidden',
            }
        )
        return False, FailedAccountDeletionRequestStatuses.ACCOUNT_NOT_ELIGIBLE

    return True, None


def request_account_deletion(
    customer, reason, detail_reason, survey_submission_uid=None
) -> Union[AccountDeletionRequest, str]:
    from juloserver.account.services.account_related import (
        process_change_account_status,
    )

    """
    Request for an account deletion.
    Args:
        customer (Customer): Customer object to be checked.
        reason (string): The reason of deletion.
        detail_reason(string): The detail reason of deletion.
    Returns:
        AccountDeletionRequest: the request created if success
        str: Status returned when not eligible / request invalid.
    """
    from juloserver.julo.services import process_application_status_change

    if not survey_submission_uid and not reason:
        logger.error(
            {
                'action': 'request_account_deletion',
                'customer_id': customer.id,
                'message': 'reason is empty',
            }
        )
        return None, FailedAccountDeletionRequestStatuses.EMPTY_REASON

    if not survey_submission_uid and not detail_reason:
        logger.error(
            {
                'action': 'request_account_deletion',
                'customer_id': customer.id,
                'message': 'reason detail is empty',
            }
        )
        return None, FailedAccountDeletionRequestStatuses.EMPTY_DETAIL_REASON

    if detail_reason and (len(detail_reason) < 40 or len(detail_reason) > 500):
        logger.error(
            {
                'action': 'request_account_deletion',
                'customer_id': customer.id,
                'detail_reason_length': len(detail_reason),
                'detail_reason': detail_reason,
                'message': 'reason detail length must be between 40 to 500 characters',
            }
        )
        return None, FailedAccountDeletionRequestStatuses.INVALID_DETAIL_REASON

    if not customer:
        return None, FailedAccountDeletionRequestStatuses.NOT_EXISTS

    is_allowed, failed_status = is_user_delete_allowed(customer)
    if not is_allowed:
        logger.error(
            {
                'action': 'request_account_deletion',
                'customer_id': customer.id,
                'failed_status': failed_status,
                'message': 'not allowed to delete',
            }
        )
        return None, failed_status

    with transaction.atomic():
        delete_request = AccountDeletionRequest(
            customer=customer,
            request_status=AccountDeletionRequestStatuses.PENDING,
            reason=reason,
            detail_reason=detail_reason,
            survey_submission_uid=survey_submission_uid,
        )
        delete_request.save()

        is_full_deletion = is_complete_deletion(customer)
        if is_full_deletion:
            account = customer.account_set.last()
            if account:
                process_change_account_status(
                    account=account,
                    new_status_code=AccountConstant.STATUS_CODE.account_deletion_on_review,
                    change_reason=AccountDeletionStatusChangeReasons.REQUEST_REASON,
                )

        for application in customer.application_set.all():
            try:
                if not application.is_julo_one_or_starter():
                    continue

                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.CUSTOMER_ON_DELETION,
                    AccountDeletionStatusChangeReasons.REQUEST_REASON,
                )
            except Exception as e:
                logger.error(
                    {
                        'action': 'request_account_deletion',
                        'message': 'cannot update application status to deletion',
                        'customer_id': customer.id,
                        'application_id': application.id,
                        'current_app_status': application.application_status_id,
                        'target_app_status': ApplicationStatusCodes.CUSTOMER_ON_DELETION,
                        'error': str(e),
                    },
                )

    send_create_deletion_request_success_email.delay(customer.id)
    return delete_request, None


def cancel_account_request_deletion(customer):
    from juloserver.customer_module.services.crm_v1 import (
        process_revert_account_status_460,
    )

    if not customer:
        return None

    current_request = customer.accountdeletionrequest_set.last()
    if not current_request:
        logger.error(
            {
                'action': 'cancel_account_request_deletion',
                'message': 'customer does not have any account deletion request',
                'customer_id': customer.id,
            }
        )
        return None

    forbidden_status = [
        AccountDeletionRequestStatuses.CANCELLED,
        AccountDeletionRequestStatuses.REJECTED,
    ]
    if current_request.request_status in forbidden_status:
        logger.error(
            {
                'action': 'cancel_account_request_deletion',
                'message': 'deletion request status already canceled or rejected',
                'customer_id': customer.id,
            }
        )
        return None

    with transaction.atomic():
        current_request.update_safely(
            request_status=AccountDeletionRequestStatuses.CANCELLED,
            verdict_reason=None,
            verdict_date=None,
            agent=None,
        )

        account = customer.account_set.last()
        if account:
            process_revert_account_status_460(
                account, AccountDeletionStatusChangeReasons.CANCEL_REASON
            )

        process_revert_applications_status_deletion(
            customer, AccountDeletionStatusChangeReasons.CANCEL_REASON
        )

    send_cancel_deletion_request_success_email.delay(customer.id)
    return current_request


def get_ongoing_account_deletion_request(customer):
    deletion_request = customer.accountdeletionrequest_set.last()
    if (
        not deletion_request
        or deletion_request.request_status not in ongoing_account_deletion_request_statuses
    ):
        return None

    return deletion_request


def get_ongoing_account_deletion_requests(customer_ids):
    if not customer_ids or len(customer_ids) <= 0:
        return []

    return AccountDeletionRequest.objects.filter(
        customer_id__in=customer_ids,
        request_status__in=ongoing_account_deletion_request_statuses,
    )


class CustomerDataChangeRequestSetting:
    def __init__(self):
        self.setting = FeatureSettingHelper(FeatureNameConst.CUSTOMER_DATA_CHANGE_REQUEST)

    @property
    def is_active(self):
        return self.setting.is_active

    @property
    def request_interval_days(self):
        return int(self.setting.get('request_interval_days', 7))

    @property
    def payslip_income_multiplier(self):
        return float(self.setting.get('payslip_income_multiplier', 1.0))

    @property
    def supported_app_version_code(self):
        return int(self.setting.get('supported_app_version_code', 2398))

    @property
    def supported_payday_version_code(self):
        return int(self.setting.get('supported_payday_version_code', 2436))


def get_customer_data_change_request_setting():
    """
    Get setting for `customer_data_change_request` feature
    Returns:
        CustomerDataChangeRequestSetting: The setting object
    """
    return CustomerDataChangeRequestSetting()


def is_show_customer_data_menu(customer: Customer) -> bool:
    """
    Check if the customer can access the "Data Pribadi" menu.
    Args:
        customer (Customer): The customer objects

    Returns:
        bool: True if the customer can access the menu, False otherwise.
    """
    return CustomerDataChangeRequestHandler(customer).is_show_customer_data_menu()


class CustomerDataChangeRequestHandler:
    def __init__(self, customer: Customer):
        self.customer = customer
        self._last_application = None
        self._last_change_request = None
        self.setting = get_customer_data_change_request_setting()

    def last_application(self) -> Application:
        """
        Get the last application of the customer.
        Returns:
            Application
        """
        if not self._last_application:
            self._last_application = self.customer.last_application

        return self._last_application

    def last_change_request(self) -> CustomerDataChangeRequest:
        """
        Get the last customer data change request of the customer.
        Returns:
            ChangeDataChangeRequest
        """
        if not self._last_change_request:
            self._last_change_request = CustomerDataChangeRequest.objects.filter(
                customer=self.customer
            ).last()
        return self._last_change_request

    def last_approved_change_request(self) -> CustomerDataChangeRequest:
        """
        Get the last approved customer data change request of the customer.
        Returns:
            ChangeDataChangeRequest
        """
        return CustomerDataChangeRequest.objects.filter(
            customer=self.customer,
            status=CustomerDataChangeRequestConst.SubmissionStatus.APPROVED,
        ).last()

    def last_submitted_change_request(self) -> CustomerDataChangeRequest:
        """
        Get the last submitted customer data change request of the customer.
        Returns:
            ChangeDataChangeRequest
        """
        return CustomerDataChangeRequest.objects.filter(
            customer=self.customer,
            status=CustomerDataChangeRequestConst.SubmissionStatus.SUBMITTED,
        ).last()

    def is_show_customer_data_menu(self) -> bool:
        """
        Check if the customer can access the "Data Pribadi" menu.
        Args:
            customer (Customer): The customer objects

        Returns:
            bool: True if the customer can access the menu, False otherwise.
        """
        if not self.setting.is_active:
            return False

        # Hide menu if the application failed application check.
        # 1. Not an active application
        # 2. Not a Julo product
        application = self.last_application()
        if (
            not application
            or application.status not in CustomerDataChangeRequestConst.ALLOWED_APPLICATION_STATUSES
            or application.product_line_id not in ProductLineCodes.julo_product()
        ):
            return False

        return True

    def is_submitted(self) -> bool:
        """
        Check if the customer has a submitted request.
        Returns:
            bool: True if the customer has a submitted request, False otherwise.
        """
        last_request = self.last_change_request()
        if last_request:
            return last_request.status == CustomerDataChangeRequestConst.SubmissionStatus.SUBMITTED

        return False

    def is_limit_reached(self) -> bool:
        """
        Check if the customer has reached the limit of request.
        Returns:
            bool: True if the customer has reached the limit of request, False otherwise.
        """
        last_request = self.last_change_request()
        if (
            not last_request
            or last_request.status != CustomerDataChangeRequestConst.SubmissionStatus.APPROVED
        ):
            return False

        now_date = timezone.localtime(timezone.now()).date()
        last_request_date = timezone.localtime(last_request.cdate).date()
        interval_day = self.setting.request_interval_days
        return (now_date - last_request_date).days < interval_day

    def get_permission_status(self) -> str:
        """
        Get the customer permission to submit customer data change request .
        Possible values:
        - 'enabled'
        - 'disabled'
        - 'not_allowed'

        Returns:
            str: The permission status.
        """
        if not self.is_show_customer_data_menu() or self.is_submitted():
            return CustomerDataChangeRequestConst.PermissionStatus.DISABLED

        if self.is_limit_reached():
            return CustomerDataChangeRequestConst.PermissionStatus.NOT_ALLOWED

        return CustomerDataChangeRequestConst.PermissionStatus.ENABLED

    def convert_application_data_to_change_request(self):
        """
        Convert application data to customer data change request.
        Returns:
            CustomerDataChangeRequest: The customer data change request.
        """
        application = self.last_application()
        if not application:
            return None

        paystub_image = Image.objects.filter(
            image_source=application.id, image_type='paystub', image_status=Image.CURRENT
        ).last()

        data = {
            'customer': self.customer,
            'application': application,
            'address': Address(
                provinsi=application.address_provinsi,
                kabupaten=application.address_kabupaten,
                kecamatan=application.address_kecamatan,
                kelurahan=application.address_kelurahan,
                kodepos=application.address_kodepos,
                detail=application.address_street_num,
            ),
            'job_type': application.job_type,
            'job_industry': application.job_industry,
            'job_description': application.job_description,
            'company_name': application.company_name,
            'company_phone_number': application.company_phone_number,
            'payday': application.payday,
            'payday_change_reason': '',
            'payday_change_proof_image_id': None,
            'paystub_image': paystub_image,
            'monthly_income': application.monthly_income,
            'monthly_expenses': application.monthly_expenses,
            'monthly_housing_cost': application.monthly_housing_cost,
            'total_current_debt': application.total_current_debt,
            'last_education': application.last_education,
        }

        return CustomerDataChangeRequest(**data)

    def store_payday_change_from_redis_to_raw_data(self, raw_data: dict) -> bool:
        """
        Store payday change data from redis to raw data.

        Args:
            raw_data (dict): The raw data that needs to be validated.
                        (CustomerDataChangeRequestSerializer)

        Returns:
            bool: True if payday change data was successfully stored, False otherwise
        """
        redis_client = get_redis_client()
        payday_change_data = redis_client.get(
            "customer_data_payday_change:" + str(self.customer.id)
        )

        if not payday_change_data:
            return False

        payday_change_data = json.loads(payday_change_data)
        raw_data['payday'] = payday_change_data['payday']
        raw_data['payday_change_reason'] = payday_change_data['payday_change_reason']
        raw_data['payday_change_proof_image_id'] = payday_change_data[
            'payday_change_proof_image_id'
        ]
        delete_document_payday_customer_change_request_from_oss(
            payday_change_data['payday_change_proof_image_id']
        )

        redis_client.delete_key("customer_data_payday_change:" + str(self.customer.id))

        return True

    def create_change_request(
        self, raw_data: dict, source: str
    ) -> Tuple[bool, Union[CustomerDataChangeRequest, str]]:
        """
        Create customer data change request.
        Args:
            raw_data (dict): The raw data that needs to be validated.
                        (CustomerDataChangeRequestSerializer)
            source (str): The source of the request.

        Returns:
            tuple[bool, Union[CustomerDataChangeRequest, str]]: A tuple containing:
                - bool: Success status
                - Union[CustomerDataChangeRequest, str]:
                    The customer data change request or error message

        Raises:
            CustomerApiException: If the raw data is invalid.
        """
        from juloserver.customer_module.serializers import (
            CustomerDataChangeRequestSerializer,
        )

        previous_change_request = self.last_approved_change_request()
        if not previous_change_request:
            previous_change_request = self.convert_application_data_to_change_request()

        version_code = raw_data.pop('version_code', 0)
        handler = CustomerDataChangeRequestHandler(customer=self.customer)

        change_request_handler = CustomerDataChangeRequestHandler(self.customer)
        if (
            version_code
            and version_code > change_request_handler.setting.supported_payday_version_code
        ):
            if previous_change_request and (previous_change_request.payday != raw_data['payday']):
                result = self.store_payday_change_from_redis_to_raw_data(raw_data)
                if not result:
                    return (
                        False,
                        "Silahkan ulangi prosesnya. "
                        "Pastikan isi dan simpan dengan cepat sebelum sesi habis, ya!",
                    )

        serializer = CustomerDataChangeRequestSerializer(
            data=raw_data,
            context={
                'change_request_handler': handler,
                'customer_id': self.customer.id,
                'version_code': version_code,
                'previous_change_request': previous_change_request,
                'payslip_income_multiplier': self.setting.payslip_income_multiplier,
            },
        )

        if not serializer.is_valid():
            raise CustomerApiException(serializer.errors)

        validated_data = serializer.validated_data
        return True, self.create_change_request_no_validation(validated_data, source)

    def create_change_request_no_validation(
        self,
        validated_data: dict,
        source: str,
    ) -> CustomerDataChangeRequest:
        """
        Create customer data change request without validation.
        Args:
            validated_data (dict): This is the value of the validated_data from the serializer
                                (CustomerDataChangeRequestCRMSerializer
            source (str): The source of the validation, either from the 'app' or 'admin'

        Returns:
            CustomerDataChangeRequest: The customer data change request.
        """
        application = self.last_application()
        previous_change_request = self.last_approved_change_request()
        if not previous_change_request:
            previous_change_request = self.convert_application_data_to_change_request()

        new_address = Address(**validated_data.get('address'))
        if previous_change_request and previous_change_request.address:
            previous_address = previous_change_request.address
            if (
                previous_address.full_address == new_address.full_address
                and previous_address.latitude == new_address.latitude
                and previous_address.longitude == new_address.longitude
            ):
                new_address = previous_address

        data = {
            'customer': self.customer,
            'application': application,
            'status': CustomerDataChangeRequestConst.SubmissionStatus.SUBMITTED,
            'address': new_address,
            'job_type': validated_data.get('job_type'),
            'job_industry': validated_data.get('job_industry'),
            'job_description': validated_data.get('job_description'),
            'company_name': validated_data.get('company_name'),
            'company_phone_number': validated_data.get('company_phone_number'),
            'company_proof_image_id': validated_data.get('company_proof_image_id'),
            'address_transfer_certificate_image_id': validated_data.get(
                'address_transfer_certificate_image_id',
            ),
            'payday': validated_data.get('payday'),
            'paystub_image_id': validated_data.get('paystub_image_id'),
            'monthly_income': validated_data.get('monthly_income'),
            'monthly_expenses': validated_data.get('monthly_expenses'),
            'monthly_housing_cost': validated_data.get('monthly_housing_cost'),
            'total_current_debt': validated_data.get('total_current_debt'),
            'source': source,
            'app_version': validated_data.get('app_version'),
            'latitude': validated_data.get('latitude'),
            'longitude': validated_data.get('longitude'),
            'last_education': validated_data.get('last_education'),
            'android_id': validated_data.get('android_id'),
            'payday_change_reason': validated_data.get('payday_change_reason'),
            'payday_change_proof_image_id': validated_data.get('payday_change_proof_image_id'),
        }

        with transaction.atomic():
            if data['address'] and data['address'].id is None:
                data['address'].save()

            return CustomerDataChangeRequest.objects.create(**data)


class CustomerDataChangeRequestNotification:
    """
    Class that handle all the notification related to customer data change request.
    """

    def __init__(self, change_request: CustomerDataChangeRequest):
        self.change_request = change_request
        self.setting = get_customer_data_change_request_setting()
        self.email_service = get_email_service()
        self.pn_client = get_julo_pn_client()
        self.device_repository = get_device_repository()

    def send_notification(self):
        """
        Send notification to customer depends on the change_request status.
        """
        from juloserver.customer_module.tasks.customer_related_tasks import (
            send_customer_data_change_request_notification_email,
            send_customer_data_change_request_notification_pn,
        )

        if not self.setting.is_active:
            return

        send_customer_data_change_request_notification_pn.delay(self.change_request.id)
        send_customer_data_change_request_notification_email.delay(self.change_request.id)

    def send_email(self):
        """
        Send email to customer depends on the change_request status.
        Returns:
            bool: True if the email is sent
        """
        if not self.setting.is_active:
            return False

        logger_data = {
            'action': 'CustomerDataChangeRequestNotification:send_email',
            'change_request_id': self.change_request.id,
            'customer_id': self.change_request.customer.id,
            'status': self.change_request.status,
        }

        template_code, email_params = self._generate_email_data()
        if template_code is None:
            logger.warning(
                {
                    'message': 'No template code found',
                    **logger_data,
                }
            )
            return False

        email_history = self.email_service.send_email(
            template_code=template_code,
            **email_params,
        )

        return email_history.sg_message_id is not None

    def send_pn(self):
        """
        Send push notification to customer depends on the change_request status.
        Returns:
            bool: True if the push notification is sent successfully, False otherwise.
        """
        if not self.setting.is_active:
            return False

        logger_data = {
            'action': 'CustomerDataChangeRequestNotification:send_pn',
            'change_request_id': self.change_request.id,
            'customer_id': self.change_request.customer.id,
            'status': self.change_request.status,
        }
        fcm_id = self.device_repository.get_active_fcm_id(self.change_request.customer.id)

        if not fcm_id:
            logger.warning(
                {
                    'message': 'No FCM ID found',
                    **logger_data,
                }
            )
            return False

        template_code, pn_data = self._generate_pn_data()
        if template_code is None:
            logger.warning(
                {
                    'message': 'No template code found',
                    **logger_data,
                }
            )
            return False

        response = self.pn_client.send_downstream_message(
            registration_ids=[fcm_id],
            template_code=template_code,
            data=pn_data,
        )
        logger.info(
            {
                'message': 'Push notification sent',
                'template_code': template_code,
                'response_status': response.status_code,
                'response_body': str(response.content),
                **logger_data,
            }
        )
        return response.status_code == 201

    def _generate_pn_data(self):
        if self.change_request.status not in (
            CustomerDataChangeRequestConst.SubmissionStatus.REJECTED,
            CustomerDataChangeRequestConst.SubmissionStatus.APPROVED,
        ):
            return None, None

        template_code = "customer_data_change_request_approved"
        title = "Perubahan Data Pribadi Disetujui"
        body = "Cek data pribadi terbaru kamu di sini, ya!"
        if self.change_request.status == CustomerDataChangeRequestConst.SubmissionStatus.REJECTED:
            template_code = "customer_data_change_request_rejected"
            title = "Perubahan Data Pribadi Ditolak"
            body = (
                "Data pribadimu gagal diubah. "
                "Kamu bisa coba ubah data lagi dalam beberapa saat, ya."
            )

        return template_code, {
            "customer_id": self.change_request.customer_id,
            "application_id": self.change_request.application_id,
            "destination_page": PageType.PROFILE,
            'title': title,
            'body': body,
        }

    def _generate_email_data(self):

        if self.change_request.status not in (
            CustomerDataChangeRequestConst.SubmissionStatus.APPROVED,
            CustomerDataChangeRequestConst.SubmissionStatus.REJECTED,
        ):
            return None, None

        changes_data, _, _ = get_customer_data_request_field_changes(self.change_request)

        email = self.change_request.customer.email
        context = self.email_service.prepare_email_context(
            self.change_request.customer,
            application_id=self.change_request.application.id,
            changes_data=changes_data,
        )

        template_path = 'customer_data/change_request_approved_email.html'
        template_code = "customer_data_change_request_approved"
        subject = "Perubahan Data Pribadi Berhasil"
        if self.change_request.status == CustomerDataChangeRequestConst.SubmissionStatus.REJECTED:
            template_path = 'customer_data/change_request_rejected_email.html'
            template_code = "customer_data_change_request_rejected"
            subject = "Perubahan Data Pribadi Gagal"

        template = get_template(template_path)
        email_content = template.render(context)

        return template_code, {
            'context': context,
            'email_to': email,
            'subject': subject,
            'content': email_content,
        }


def get_customer_data_request_field_changes(change_request: CustomerDataChangeRequest):
    from juloserver.customer_module.serializers import (
        CustomerDataChangeRequestCompareSerializer,
    )

    # Original Data
    current_data = CustomerDataChangeRequestCompareSerializer(instance=change_request).data
    previous_request = change_request.previous_approved_request
    if previous_request:
        compare_data = CustomerDataChangeRequestCompareSerializer(instance=previous_request).data
    else:
        change_request_handler = CustomerDataChangeRequestHandler(change_request.customer)
        original_data_obj = change_request_handler.convert_application_data_to_change_request()
        compare_data = CustomerDataChangeRequestCompareSerializer(instance=original_data_obj).data

    changes_data = []
    for field, value in current_data.items():
        if field not in compare_data or value != compare_data[field]:
            changes_data.append(
                (
                    field,
                    CustomerDataChangeRequestConst.Field.LABEL_MAP[field],
                    compare_data[field] if field in compare_data else None,
                    value,
                )
            )

    return changes_data, compare_data, current_data


def increment_device_reset_phone_number_rate_limiter(
    android_id: str,
    feature_setting: MobileFeatureSetting,
) -> None:

    redis_client = get_redis_client()
    date = str(timezone.localtime(timezone.now()).date())
    key = 'customer_module:reset-phone-number-{}-{}'.format(android_id, date)

    ttl = seconds_until_end_of_day()
    redis_client.increment(key)
    redis_client.expire(key=key, expire_time=ttl)

    return None


def is_device_reset_phone_number_rate_limited(
    android_id: str,
    feature_setting: MobileFeatureSetting,
) -> bool:

    if android_id is None:
        return False

    redis_client = get_redis_client()

    date = str(timezone.localtime(timezone.now()).date())
    key = 'customer_module:reset-phone-number-{}-{}'.format(android_id, date)

    max_count = int(feature_setting.parameters.get('max_count'))
    count = redis_client.get(key)
    if not count:
        return False

    return int(count) >= max_count


def prepare_reset_phone_request(
    customer: Customer,
    feature_setting: MobileFeatureSetting,
) -> Union[None, str]:
    """
    this function is to prepare reset phone number request.
    currently, this is only for reset_phone_number mobile feature settings.
    other feature settings can reuse only when they have the required parameters
    Args:
        customer: Customer object
        feature_setting: MobileFeatureSetting object
    Returns:
        reset_key: str
    """

    if feature_setting.feature_name != MobileFeatureNameConst.RESET_PHONE_NUMBER:
        return None

    request_time = feature_setting.parameters.get('link_exp_time')

    reset_key = generate_phone_number_key(customer.phone)
    customer.reset_password_key = reset_key
    reset_pin_exp_date = timezone.localtime(timezone.now()) + timedelta(
        days=request_time.get('days'),
        hours=request_time.get('hours'),
        minutes=request_time.get('minutes'),
    )

    customer.reset_password_exp_date = reset_pin_exp_date
    customer.save(update_fields=['reset_password_key', 'reset_password_exp_date'])

    return reset_key


def process_incoming_change_phone_number_request(
    customer: Customer,
    android_id: str,
) -> Union[None, str]:
    """
    Args:
        customer_id: int
    """

    feature_setting = MobileFeatureSetting.objects.get(
        feature_name=MobileFeatureNameConst.RESET_PHONE_NUMBER,
        is_active=True,
    )

    if not feature_setting:
        return ChangePhoneLostAccess.ErrorMessages.DEFAULT

    if is_device_reset_phone_number_rate_limited(
        android_id,
        feature_setting,
    ):
        return ChangePhoneLostAccess.ErrorMessages.RATE_LIMIT_ERROR

    increment_device_reset_phone_number_rate_limiter(
        android_id,
        feature_setting,
    )

    # detokenize customer here
    if not customer.account or not customer.phone:
        return ChangePhoneLostAccess.ErrorMessages.DEFAULT

    deletion_requests = get_ongoing_account_deletion_requests([customer.id])
    if deletion_requests:
        return ChangePhoneLostAccess.ErrorMessages.DEFAULT

    if customer.application_set.filter(
        application_status__in=ChangePhoneLostAccess.FORBIDDEN_APPLICATION_STATUS
    ).exists():
        return ChangePhoneLostAccess.ErrorMessages.DEFAULT

    if customer.account.status_id in ChangePhoneLostAccess.FORBIDDEN_ACCOUNT_STATUS:
        return ChangePhoneLostAccess.ErrorMessages.DEFAULT

    reset_key = prepare_reset_phone_request(
        customer=customer,
        feature_setting=feature_setting,
    )

    send_reset_phone_number_email_task.delay(customer, reset_key)

    return None


def submit_customer_product_locked(customer_id, validated_data):
    return CustomerProductLocked.objects.create(customer_id=customer_id, **validated_data)


def is_user_survey_allowed(customer: Customer) -> Union[bool, str]:
    """
    Checks if customer is eligible for submit account deletion survey.
    Args:
        customer (Customer): Customer object to be checked.
    Returns:
        bool: True if eligible. False if not.
        str: Status returned when not eligible.
    """

    active_loan_ids = get_active_loan_ids(customer)
    if active_loan_ids and len(active_loan_ids) > 0:
        logger.warning(
            {
                'action': 'is_user_survey_allowed',
                'customer_id': customer.id,
                'active_loan_ids': active_loan_ids,
                'message': 'not allowed to delete, have active loans',
            }
        )
        return False, FailedAccountDeletionRequestStatuses.ACTIVE_LOANS

    application = customer.application_set.last()
    if (
        application
        and application.application_status_id in forbidden_application_status_account_deletion
    ):
        logger.warning(
            {
                'action': 'is_user_survey_allowed',
                'customer_id': customer.id,
                'application_id': application.id,
                'application_status_id': application.application_status_id,
                'message': 'not allowed to delete, application status forbidden',
            }
        )
        return False, FailedAccountDeletionRequestStatuses.APPLICATION_NOT_ELIGIBLE

    return True, None


def get_customer_transactions(customer_id: str) -> list:
    """
    This function to get the customer's active loan for some transaction methods

    Args:
        customer_id: int -> id of the customer,

    Returns:
        List
            -> Empty means there is no active loan data
            -> Any means there are some active loan data
    """

    from juloserver.cx_complaint_form.models import ComplaintSubTopic

    # get active loan by filtering customer id and active status mapping
    loans = get_active_loan_by_customer_id(customer_id)

    results = []

    if not loans:
        return results

    subtopic_complaint_form = ComplaintSubTopic.objects.filter(
        topic__slug="latest-transaction"
    ).first()

    if not subtopic_complaint_form:
        return results

    for loan in loans.iterator():
        # mapping loan status based on status code
        loan_status = get_loan_status_by_mapping_status_code(loan)

        # construct response data
        loan_record = {
            "complaint_sub_topic_id": subtopic_complaint_form.id,
            "loan": {
                "loan_xid": loan.loan_xid,
                "loan_date": timezone.localtime(loan.cdate),
                "status_code": loan.loan_status.status_code,
                "status": loan_status,
                "amount": loan.loan_amount,
                "installment_amount": loan.installment_amount,
            },
            "transaction_method": {
                "transaction_method_id": loan.transaction_method.pk,
                "name": loan.transaction_method.method,
                "slug": slugify(loan.transaction_method.fe_display_name),
                "display_name": loan.transaction_method.fe_display_name,
                "foreground_icon": loan.transaction_method.foreground_icon_url,
                "background_icon": loan.transaction_method.background_icon_url,
            },
            "transaction": {
                "name": "",
                "account_bank": "",
                "account_number": "",
                "account_name": "",
                "account_detail": "",
            },
        }

        transaction_data = [
            get_commerce_transaction(loan),
            get_healthcare_transaction(loan),
            get_school_transaction(loan),
            get_sepulsa_transaction(loan),
            get_ayoconnect_transaction(loan),
        ]

        # find kind of transaction, and update data if exists
        for data in transaction_data:
            if data:
                loan_record["transaction"] = data
                results.append(loan_record)
                break  # Exit after first matching transaction typeW

    return results


def get_active_loan_by_customer_id(customer_id) -> Loan:
    from juloserver.julo.models import StatusLookup

    active_loan_status = [
        StatusLookup.CURRENT_CODE,
        StatusLookup.LENDER_APPROVAL,
        StatusLookup.FUND_DISBURSAL_ONGOING,
        StatusLookup.MANUAL_FUND_DISBURSAL_ONGOING,
        StatusLookup.LOAN_1DPD_CODE,
        StatusLookup.LOAN_5DPD_CODE,
        StatusLookup.LOAN_30DPD_CODE,
        StatusLookup.LOAN_60DPD_CODE,
        StatusLookup.LOAN_90DPD_CODE,
        StatusLookup.LOAN_120DPD_CODE,
        StatusLookup.LOAN_150DPD_CODE,
        StatusLookup.LOAN_180DPD_CODE,
        StatusLookup.RENEGOTIATED_CODE,
        StatusLookup.FUND_DISBURSAL_FAILED,
    ]

    loans = (
        Loan.objects.filter(customer_id=customer_id)
        .annotate(
            category_product_name=F('transaction_method__fe_display_name'),
            school_name=F('loanstudentregister__student_register__school__name'),
            student_fullname=F('loanstudentregister__student_register__student_fullname'),
            note=F('loanstudentregister__student_register__note'),
        )
        .filter(loan_status__in=active_loan_status)
        .exclude(
            transaction_method__method__in=[
                "j-financing",
                "credit card",
                "qris",
                "qris_1",
                "balance_consolidation",
                "pfm",
            ]
        )
        .order_by("-pk")[:5]
    )

    return loans


def get_loan_status_by_mapping_status_code(loan: Loan) -> str:
    from juloserver.julo.models import StatusLookup

    if (
        loan.loan_status.status_code > StatusLookup.INACTIVE_CODE
        and loan.loan_status.status_code <= StatusLookup.MANUAL_FUND_DISBURSAL_ONGOING
    ):
        status = "Sedang diproses"
    elif loan.loan_status.status_code >= StatusLookup.CURRENT_CODE:
        status = "Berhasil"
    else:
        status = "Gagal"

    return status


def get_detail_tarik_kirim_dana_transaction(loan: Loan) -> dict:
    from juloserver.payment_point.constants import TransactionMethodCode

    data = {}

    if (
        loan.transaction_method_id == TransactionMethodCode.SELF.code
        or loan.transaction_method_id == TransactionMethodCode.OTHER.code
    ):
        data["name"] = loan.transaction_method.fe_display_name
        data["account_bank"] = loan.bank_account_destination.bank.bank_name_frontend
        data["account_number"] = loan.bank_account_destination.name_bank_validation.account_number
        data["account_name"] = (
            loan.bank_account_destination.name_bank_validation.validated_name
            if loan.bank_account_destination.name_bank_validation.validated_name
            else ""
        )
        data["account_detail"] = (
            loan.bank_account_destination.bank.bank_name_frontend
            + " VA - "
            + loan.bank_account_destination.name_bank_validation.account_number
        )

    return data


def get_commerce_transaction(loan: Loan) -> dict:
    from juloserver.customer_module.services.bank_account_related import (
        is_ecommerce_bank_account,
    )

    data = {}

    if is_ecommerce_bank_account(loan.bank_account_destination):
        data["name"] = loan.bank_account_destination.description
        data["account_bank"] = (
            loan.bank_account_destination.bank.bank_name_frontend
            if loan.bank_account_destination
            else ""
        )
        data["account_number"] = (
            loan.bank_account_destination.name_bank_validation.account_number
            if loan.bank_account_destination
            else ""
        )
        data["account_name"] = (
            loan.bank_account_destination.name_bank_validation.validated_name
            if loan.bank_account_destination.name_bank_validation.validated_name
            else ""
        )
        data["account_detail"] = (
            (
                loan.bank_account_destination.bank.bank_name_frontend
                + " VA - "
                + loan.bank_account_destination.name_bank_validation.account_number
            )
            if loan.bank_account_destination
            else ""
        )

    return data


def get_healthcare_transaction(loan: Loan) -> dict:
    from juloserver.healthcare.models import HealthcareUser

    data = {}
    if loan.is_healthcare_product:
        healthcare_user = (
            HealthcareUser.objects.select_related('healthcare_platform')
            .filter(loans__loan_id=loan.pk)
            .first()
        )

        data["name"] = healthcare_user.healthcare_platform.name
        data["account_bank"] = (
            loan.bank_account_destination.bank.bank_name_frontend
            if loan.bank_account_destination
            else ""
        )
        data["account_name"] = (
            loan.bank_account_destination.name_bank_validation.validated_name
            if loan.bank_account_destination.name_bank_validation.validated_name
            else ""
        )
        data["account_number"] = (
            loan.bank_account_destination.name_bank_validation.account_number
            if loan.bank_account_destination
            else ""
        )
        data["account_detail"] = (
            (
                loan.bank_account_destination.bank.bank_name_frontend
                + " - "
                + loan.bank_account_destination.name_bank_validation.account_number
                + " - "
                + healthcare_user.healthcare_platform.name
            )
            if loan.bank_account_destination
            else ""
        )

    return data


def get_sepulsa_transaction(loan: Loan) -> dict:
    from juloserver.julo.models import SepulsaTransaction
    from juloserver.payment_point.constants import (
        SepulsaProductCategory,
        SepulsaProductType,
    )

    data = {}
    sepulsa_transaction = SepulsaTransaction.objects.filter(loan=loan).first()
    if sepulsa_transaction:  # ppob sepulsa transaction
        name = account_number = account_bank = account_name = account_detail = ""
        if sepulsa_transaction.product.category == SepulsaProductCategory.POSTPAID[0]:
            name = loan.transaction_method.fe_display_name
            account_number = sepulsa_transaction.phone_number
            account_detail = sepulsa_transaction.phone_number
        elif sepulsa_transaction.product.type == SepulsaProductType.EWALLET:
            name = sepulsa_transaction.product.product_name
            account_number = sepulsa_transaction.phone_number
            account_detail = sepulsa_transaction.phone_number
        elif sepulsa_transaction.product.type == SepulsaProductType.ELECTRICITY:
            if sepulsa_transaction.product.category == SepulsaProductCategory.ELECTRICITY_PREPAID:
                name = sepulsa_transaction.product.product_name
            elif (
                sepulsa_transaction.product.category == SepulsaProductCategory.ELECTRICITY_POSTPAID
            ):
                name = loan.transaction_method.fe_display_name

            account_number = sepulsa_transaction.customer_number
            account_detail = sepulsa_transaction.customer_number
        elif sepulsa_transaction.product.type == SepulsaProductType.BPJS:
            name = loan.transaction_method.fe_display_name
            account_number = sepulsa_transaction.customer_number
            account_detail = sepulsa_transaction.customer_number
        elif sepulsa_transaction.product.type == SepulsaProductType.PDAM:
            name = sepulsa_transaction.product.product_label
            account_number = sepulsa_transaction.customer_number
            account_detail = sepulsa_transaction.customer_number
        elif sepulsa_transaction.product.type == SepulsaProductType.TRAIN_TICKET:
            account_name = account_detail = "-"
            train_transaction = sepulsa_transaction.traintransaction_set.last()
            if train_transaction:
                depart_station = train_transaction.depart_station
                destination_station = train_transaction.destination_station
                name = "{} ({}) - {} ({})".format(
                    depart_station.name,
                    depart_station.code,
                    destination_station.name,
                    destination_station.code,
                )
                account_detail = (
                    str(train_transaction.adult + train_transaction.infant) + " Penumpang"
                )
        elif sepulsa_transaction.product.type == SepulsaProductType.MOBILE:
            name = sepulsa_transaction.product.product_name
            account_number = sepulsa_transaction.phone_number
            account_detail = sepulsa_transaction.phone_number

        data["name"] = name
        data["account_bank"] = account_bank
        data["account_number"] = account_number
        data["account_name"] = account_name
        data["account_detail"] = account_detail

    else:
        data = get_non_ppob_transaction(loan)

    return data


def get_ayoconnect_transaction(loan: Loan) -> dict:
    from juloserver.payment_point.models import AYCEWalletTransaction

    data = {}
    ayc_transaction = AYCEWalletTransaction.objects.filter(loan=loan).first()

    if ayc_transaction:  # ppob ayoconnect transaction
        data["name"] = ayc_transaction.ayc_product.product_name
        data["account_number"] = ayc_transaction.phone_number
        data["account_detail"] = ayc_transaction.phone_number

    return data


def get_non_ppob_transaction(loan: Loan) -> dict:
    data = {}

    if loan.bank_account_destination:
        if loan.bank_account_destination.bank:
            data["name"] = loan.transaction_method.fe_display_name
        if loan.bank_account_destination.name_bank_validation:
            data["account_bank"] = (
                loan.bank_account_destination.bank.bank_name_frontend
                if loan.bank_account_destination
                else ""
            )
            data["account_name"] = (
                loan.bank_account_destination.name_bank_validation.validated_name
                if loan.bank_account_destination
                and loan.bank_account_destination.name_bank_validation.validated_name
                else ""
            )
            data[
                "account_number"
            ] = loan.bank_account_destination.name_bank_validation.account_number
            detail = (
                (
                    loan.bank_account_destination.bank.bank_name_frontend
                    + " - "
                    + loan.bank_account_destination.name_bank_validation.account_number
                )
                if loan.bank_account_destination
                else ""
            )
            data["account_detail"] = (
                detail + " - " + loan.bank_account_destination.name_bank_validation.validated_name
                if loan.bank_account_destination
                and loan.bank_account_destination.name_bank_validation.validated_name
                else detail
            )

    return data


def get_school_transaction(loan: Loan) -> dict:
    data = {}

    if loan.school_name:  # school transaction
        data["name"] = loan.school_name
        data["account_bank"] = (
            loan.bank_account_destination.bank.bank_name_frontend
            if loan.bank_account_destination
            else ""
        )
        data["account_name"] = (
            loan.bank_account_destination.name_bank_validation.validated_name
            if loan.bank_account_destination.name_bank_validation.validated_name
            else ""
        )
        data["account_number"] = loan.bank_account_destination.name_bank_validation.account_number
        data["account_detail"] = (
            (
                loan.bank_account_destination.bank.bank_name_frontend
                + " - "
                + loan.bank_account_destination.name_bank_validation.account_number
                + " - "
                + loan.school_name
            )
            if loan.bank_account_destination
            else ""
        )

    return data


def delete_document_payday_customer_change_request_from_oss(document_id: int) -> bool:
    """
    Delete image from OSS

    This function deletes an image from the OSS (Object Storage Service)
    based on the provided image ID.

    Args:
        image_id (str): The ID of the image to be deleted.

    Returns:
        None
    """

    if not document_id or not isinstance(document_id, int):
        return False

    document = CXDocument.objects.filter(pk=document_id).first()
    if not document:
        return False

    url = urlparse(document.document_url)
    path_file = url.path

    try:
        delete_public_file_from_oss(settings.OSS_MEDIA_BUCKET, path_file)
        return True
    except Exception as e:
        logger.error(
            {
                'action': 'delete_public_file_from_oss',
                'data': str(e),
                'response': "Failed to delete file from OSS",
            }
        )
        return False


def is_consent_withdrawal_allowed(customer: Customer) -> Union[bool, str]:
    """
    Check if consent withdrawal is allowed for a given customer.

    Args:
        customer (Customer): The customer object.

    Returns:
        Union[bool, str]: A tuple containing a boolean value indicating whether
        consent withdrawal is allowed,
        and a string representing the reason if it is not allowed.
    """

    # Check for loans in disbursement
    if Loan.objects.filter(
        customer_id=customer.id,
        loan_status_id__in=ConsentWithdrawal.forbidden_loan_status,
    ).exists():
        logger.warning(
            {
                'action': 'is_consent_withdrawal_allowed',
                'customer_id': customer.id,
                'message': 'not allowed to withdraw consent data, have on disbursement loan',
            }
        )
        return False, ConsentWithdrawal.FailedRequestStatuses.LOANS_ON_DISBURSEMENT

    # Check for active loans
    active_loans = get_active_loan_by_customer_id(customer)
    if active_loans:
        active_loan_ids = tuple(loan.id for loan in active_loans)
        logger.warning(
            {
                'action': 'is_consent_withdrawal_allowed',
                'customer_id': customer.id,
                'active_loan_ids': active_loan_ids,
                'message': 'not allowed to withdraw consent data, have active loans',
            }
        )
        return False, ConsentWithdrawal.FailedRequestStatuses.ACTIVE_LOANS

    # Check application status
    application = customer.application_set.last()
    if (
        application
        and application.application_status_id in ConsentWithdrawal.forbidden_application_status
    ):
        logger.warning(
            {
                'action': 'is_consent_withdrawal_allowed',
                'customer_id': customer.id,
                'application_id': application.id,
                'application_status_id': application.application_status_id,
                'message': 'not allowed to withdraw consent data, application status forbidden',
            }
        )
        return False, ConsentWithdrawal.FailedRequestStatuses.APPLICATION_NOT_ELIGIBLE

    # Check account status
    account = customer.account_set.last()
    if account and account.status_id in ConsentWithdrawal.forbidden_account_status:
        logger.warning(
            {
                'action': 'is_consent_withdrawal_allowed',
                'customer_id': customer.id,
                'account_id': account.id,
                'account_status_id': account.status_id,
                'message': 'not allowed to withdraw consent data, account status forbidden',
            }
        )
        return False, ConsentWithdrawal.FailedRequestStatuses.ACCOUNT_NOT_ELIGIBLE

    return True, None


def request_consent_withdrawal(
    customer: Customer,
    source: str,
    reason: str,
    detail_reason: str,
    email_requestor: str = None,
    action_by: int = None,
) -> Union[ConsentWithdrawalRequest, str]:
    """
    Request withdrawal of consent for a customer.

    Args:
        customer: The customer object.
        reason: The reason for the consent withdrawal.
        detail_reason: The detailed reason for the consent withdrawal.
        email_requestor: The email of the person requesting the withdrawal.
        action_by: The ID of the user performing the action.

    Returns:
        A tuple containing the withdrawal request object and an error status, if any.
    """
    from juloserver.account.services.account_related import (
        process_change_account_status,
    )
    from juloserver.customer_module.services.crm_v1 import (
        process_revert_account_status,
        process_revert_applications_status,
    )
    from juloserver.julo.services import process_application_status_change

    # Validate inputs
    if not customer:
        return None, ConsentWithdrawal.FailedRequestStatuses.NOT_EXISTS

    if not reason:
        logger.error(
            {
                'action': 'request_consent_withdrawal',
                'customer_id': customer.id,
                'message': 'reason is empty',
            }
        )
        return None, ConsentWithdrawal.FailedRequestStatuses.EMPTY_REASON

    if reason == "lainnya" and not detail_reason:
        logger.error(
            {
                'action': 'request_consent_withdrawal',
                'customer_id': customer.id,
                'message': "reason detail is empty",
            }
        )
        return None, ConsentWithdrawal.FailedRequestStatuses.EMPTY_DETAIL_REASON

    if detail_reason:
        is_invalid = (
            not action_by
            and not (
                ConsentWithdrawal.MIN_REASON_LENGTH_INAPP
                <= len(detail_reason)
                <= ConsentWithdrawal.MAX_REASON_LENGTH
            )
        ) or (action_by and len(detail_reason) < ConsentWithdrawal.MIN_REASON_LENGTH_CRM)

        if is_invalid:
            logger.error(
                {
                    'action': 'request_account_deletion',
                    'customer_id': customer.id,
                    'detail_reason_length': len(detail_reason),
                    'detail_reason': detail_reason,
                    'message': "Length of detail reason is not valid",
                }
            )
            if not action_by:
                return (
                    None,
                    ConsentWithdrawal.FailedRequestStatuses.INVALID_LENGTH_DETAIL_REASON_INAPP,
                )
            else:
                return (
                    None,
                    ConsentWithdrawal.FailedRequestStatuses.INVALID_LENGTH_DETAIL_REASON_CRM,
                )

    # Check if withdrawal is allowed
    action_attr = ConsentWithdrawal.MAPPING_ACTION_ATTRS["request"]
    is_allowed, failed_status = is_consent_withdrawal_allowed(customer)
    if not is_allowed:
        logger.error(
            {
                'action': action_attr["log_error"],
                'customer_id': customer.id,
                'failed_status': failed_status,
                'message': 'not allowed to withdraw consent data',
            }
        )
        return None, failed_status

    with transaction.atomic():
        # Check for existing request
        status_filter = (
            [action_attr["from_status"]]
            if not isinstance(action_attr["from_status"], list)
            else action_attr["from_status"]
        )
        existing_request = ConsentWithdrawalRequest.objects.filter(customer_id=customer.id).last()
        if existing_request and existing_request.status == 'requested':
            return None, ConsentWithdrawal.FailedRequestStatuses.ALREADY_REQUESTED

        if existing_request and existing_request.status not in status_filter:
            return None, ConsentWithdrawal.FailedRequestStatuses.ALREADY_WITHDRAWN

        # Set default values
        email_requestor = email_requestor or customer.email
        action_by = action_by or customer.id

        # Get application ID if exists
        has_applications = customer.application_set.exists()
        application_id = customer.application_set.last().id if has_applications else None

        # Create withdrawal request
        withdrawal_request = ConsentWithdrawalRequest.objects.create(
            customer_id=customer.id,
            user_id=customer.user_id,
            email_requestor=email_requestor,
            status=action_attr["to_status"],
            source=source,
            application_id=application_id,
            reason=reason,
            detail_reason=detail_reason,
            action_by=action_by,
            action_date=timezone.localtime(timezone.now()),
        )

        # Update account status if exists
        account = customer.account_set.last()
        if account:
            process_change_account_status(
                account=account,
                new_status_code=AccountConstant.STATUS_CODE.consent_withdrawal_requested,
                change_reason=action_attr["reason"],
            )

        # Process applications
        errors = 0
        target_status = ApplicationStatusCodes.CUSTOMER_ON_CONSENT_WITHDRAWAL

        if has_applications:
            for application in customer.application_set.all():
                if (
                    not application.is_julo_one_or_starter()
                    or application.status == ApplicationStatusCodes.LOC_APPROVED
                ):
                    continue

                try:
                    process_application_status_change(
                        application.id,
                        target_status,
                        action_attr["reason"],
                    )
                except (JuloInvalidStatusChange, Exception) as e:
                    sentry_client.captureException()
                    logger.error(
                        {
                            'action': action_attr["log_error"],
                            'message': 'cannot update application status to withdraw consent data',
                            'customer_id': customer.id,
                            'application_id': application.id,
                            'current_app_status': application.application_status_id,
                            'target_app_status': target_status,
                            'error': str(e),
                        }
                    )
                    errors += 1

        # Handle errors if any
        if errors > 0:
            withdrawal_request.delete()
            revert_message = (
                "cancelled consent withdrawal request because failed to update application status"
            )

            if account:
                process_revert_account_status(
                    account, action_attr["account_status"], revert_message
                )

            if has_applications:
                process_revert_applications_status(
                    customer, action_attr["application_status"], revert_message
                )

            return None, ConsentWithdrawal.FailedRequestStatuses.FAILED_CHANGE_STATUS

        # Send email notification
        send_consent_withdraw_email.delay("request", customer_id=customer.id)
        return withdrawal_request, None


def process_action_consent_withdrawal(
    customer: Customer,
    action: str,
    source: str,
    admin_reason: Optional[str] = None,
    email_requestor: str = None,
    action_by: int = None,
) -> Union[ConsentWithdrawalRequest, None]:
    """
    Process the action of consent withdrawal for a customer.

    Args:
        customer: The customer object containing user information.
        action: The action string to be performed for consent withdrawal.
        email_requestor: The email of the person requesting the withdrawal.
        action_by: The ID of the user performing the action.

    Returns:
        ConsentWithdrawalRequest: The last consent withdrawal request object if found.
        None: If no customer provided or no current request found.
    """
    from juloserver.customer_module.services.crm_v1 import (
        process_revert_account_status,
        process_revert_applications_status,
    )

    if not customer:
        return None

    action_attr = ConsentWithdrawal.MAPPING_ACTION_ATTRS[action]
    status_filter = (
        [action_attr["from_status"]]
        if not isinstance(action_attr["from_status"], list)
        else action_attr["from_status"]
    )

    current_request = ConsentWithdrawalRequest.objects.filter(customer_id=customer.id).last()
    if not current_request or current_request.status not in status_filter:
        logger.error(
            {
                'action': action_attr["log_error"],
                'message': action_attr["log_message"],
                'customer_id': customer.id,
                'current_request_status': current_request.status if current_request else None,
            }
        )
        return None

    with transaction.atomic():
        if not email_requestor:
            email_requestor = current_request.email_requestor

        if not action_by:
            action_by = customer.id

        withdrawal_obj = ConsentWithdrawalRequest.objects.create(
            customer_id=customer.id,
            user_id=customer.user_id,
            email_requestor=email_requestor,
            status=action_attr["to_status"],
            source=source,
            application_id=current_request.application_id,
            reason=current_request.reason,
            detail_reason=current_request.detail_reason,
            action_by=action_by,
            admin_reason=admin_reason,
            action_date=timezone.localtime(timezone.now()),
        )

        # Process account status reversion if account exists
        account = customer.account_set.last()
        if account:
            process_revert_account_status(
                account, action_attr["account_status"], action_attr["reason"]
            )

        # Process applications status reversion if applications exist
        if customer.application_set.exists():
            process_revert_applications_status(
                customer, action_attr["application_status"], action_attr["reason"]
            )

        # Send email notification for cancellations
        if action in ["cancel", "reject", "regrant"]:
            send_consent_withdraw_email.delay(action, customer_id=customer.id)

        return withdrawal_obj


def get_consent_status_from_application_or_account(customer: Customer) -> str:
    # Check Application status and Account status have withdrawal consent
    application = customer.application_set.last()
    if not application:
        return None

    withdrawal_request = ConsentWithdrawal.STATUS_TO_REQUEST_STATUS.get(
        application.application_status_id
    )
    if withdrawal_request:
        return withdrawal_request

    if application.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
        account = customer.account_set.last()
        if not account:
            return None

        withdrawal_request = ConsentWithdrawal.STATUS_TO_REQUEST_STATUS.get(account.status_id)
        if withdrawal_request:
            return withdrawal_request

    return None


def check_consent_withdrawal(customer: Customer) -> Union[bool, str]:
    withdraw_consent_status = get_consent_status_from_application_or_account(customer)
    if withdraw_consent_status:
        return True, ConsentWithdrawal.RestrictionMessages.consent_withdrawal_messages().get(
            withdraw_consent_status
        )

    # check have withdrawal request with status (pending/approved)
    consent_withdraw_request = ConsentWithdrawalRequest.objects.filter(
        customer_id=customer.pk
    ).last()
    if consent_withdraw_request is None:
        return False, ''

    if consent_withdraw_request.status == 'requested':
        return True, ConsentWithdrawal.RestrictionMessages.TAG_CONSENT_WITHDRAWAL_REQUESTED

    if (
        consent_withdraw_request.status == 'approved'
        or consent_withdraw_request.status == 'auto_approved'
    ):
        return True, ConsentWithdrawal.RestrictionMessages.TAG_CONSENT_WITHDRAWAL_APPROVED

    return False, ''


def restriction_access(customer: Customer) -> Tuple[bool, List[str]]:
    is_feature_lock_withdraw_consent, status_withdraw_consent = check_consent_withdrawal(customer)

    restrictions = [status_withdraw_consent] if status_withdraw_consent else []
    return is_feature_lock_withdraw_consent, restrictions


def get_latest_requested_consent_withdraw_date(customer_id: int):
    qs = ConsentWithdrawalRequest.get_by_customer_and_status(
        customer_id=customer_id, statuses=["requested"]
    )

    return qs.order_by("-cdate").values_list("cdate", flat=True).first()


def get_consent_withdrawal_status(customer: Customer) -> str:
    """
    Get the status of consent withdrawal for a customer.

    Args:
        customer (Customer): The customer object.

    Returns:
        str: The status of consent withdrawal.
    """

    consent_withdrawal_status = get_consent_status_from_application_or_account(customer)
    if consent_withdrawal_status:
        consent_withdraw_request_qs = ConsentWithdrawalRequest.get_by_customer_and_status(
            customer_id=customer.id, statuses=[consent_withdrawal_status]
        )

        consent_withdraw_request = consent_withdraw_request_qs.last()
        if consent_withdraw_request:
            consent_withdraw_request.action_date = get_latest_requested_consent_withdraw_date(
                customer.id
            )

            return consent_withdraw_request

    consent_withdraw_request = ConsentWithdrawalRequest.objects.filter(
        customer_id=customer.pk
    ).last()
    if consent_withdraw_request:
        consent_withdraw_request.action_date = get_latest_requested_consent_withdraw_date(
            customer.id
        )
        return consent_withdraw_request

    return None


def send_web_consent_withdrawal_received_failed(
    email: str,
):
    """
    Send an email notification to the customer indicating
    that their consent withdrawal request has failed.

    Args:
        email (str): The email address of the customer.

    Returns:
        None
    """

    first_name = get_first_name(None)

    subject = "Permintaan Penarikan Persetujuan Gagal"
    variable = {"first_name": first_name}
    template = get_template('web_consent_withdrawal_rejected.html')
    html_content = template.render(variable)

    # Send the email with the rendered HTML content
    send_email_with_html(
        subject,
        html_content,
        email,
        ConsentWithdrawal.EMAIL_CS,
        'web_consent_withdrawal_rejected',
    )


def delete_ktp_and_selfie_file_from_oss(
    image_ktp_filepath: str,
    image_selfie_filepath: str,
):
    """
    Delete KTP and selfie files from OSS (Object Storage Service).

    Args:
        image_ktp_filepath (str): File path of the KTP image in OSS.
        image_selfie_filepath (str): File path of the selfie image in OSS.

    Returns:
        None
    """

    try:
        # Delete the KTP image file from OSS
        delete_public_file_from_oss(
            settings.OSS_PUBLIC_BUCKET,
            image_ktp_filepath,
        )
    except Exception as e:
        logger.error(
            {
                'action': 'delete_public_file_from_oss',
                'usage': 'image_ktp_filepath',
                'data': str(e),
                'response': "Failed to delete file from OSS",
            }
        )

    try:
        # Delete the selfie image file from OSS
        delete_public_file_from_oss(
            settings.OSS_PUBLIC_BUCKET,
            image_selfie_filepath,
        )
    except Exception as e:
        logger.error(
            {
                'action': 'delete_public_file_from_oss',
                'usage': 'image_selfie_filepath',
                'data': str(e),
                'response': "Failed to delete file from OSS",
            }
        )

    return


def forward_web_consent_withdrawal_request_to_ops(
    fullname,
    phone,
    email,
    reason,
    reason_detail,
    image_ktp,
    image_ktp_file_path,
    image_selfie,
    image_selfie_file_path,
):
    """
    Forward the web consent withdrawal request to the operations team.

    Args:
        fullname (str): Full name of the customer.
        phone (str): Phone number of the customer.
        email (str): Email address of the customer.
        reason (str): Reason for the consent withdrawal.
        reason_detail (str): Additional details for the consent withdrawal.
        image_ktp (bytes): KTP image data.
        image_ktp_file_path (str): File path of the KTP image.
        image_selfie (bytes): Selfie image data.
        image_selfie_file_path (str): File path of the selfie image.

    Returns:
        None
    """

    subject_prefix = ''
    recipient_email = ConsentWithdrawal.EMAIL_CS
    if settings.ENVIRONMENT != 'prod':
        subject_prefix = '[Squad8QAtest] '
        recipient_email = "heru.apriatama@julofinance.com,rasyidyellowtest@gmail.com"

    subject = subject_prefix + "Permintaan Penarikan Persetujuan Akun"
    template = get_template("consent_withdrawal/web_consent_withdrawal_forward_to_cs.html")
    variable = {
        "fullname": fullname,
        "phone": phone,
        "email": email,
        "reason": reason,
        "reason_detail": reason_detail,
    }
    html_content = template.render(variable)
    sender_email = email

    # Extract file extension for KTP image
    image_ktp_extension = image_ktp_file_path.split('.')[-1]
    image_ktp_attachment = generate_image_attachment(
        image=image_ktp,
        filename="ktp-" + fullname,
        ext=image_ktp_extension,
    )

    # Extract file extension for selfie image
    image_selfie_extension = image_selfie_file_path.split('.')[-1]
    image_selfie_attachment = generate_image_attachment(
        image=image_selfie,
        filename="selfie-" + fullname,
        ext=image_selfie_extension,
    )

    # Send email with HTML content and attachments
    send_email_with_html(
        subject=subject,
        html_content=html_content,
        recipient_email=recipient_email,
        sender_email=sender_email,
        template_code='web_consent_withdrawal_forward_to_cs',
        attachments=[image_ktp_attachment, image_selfie_attachment],
        fullname=fullname,
    )


def send_web_consent_withdrawal_received_success(
    customer: Customer,
):
    """
    Send an email notification to the customer indicating
    that their consent withdrawal request has been received successfully.

    Args:
        customer (Customer): The customer object.

    Returns:
        None
    """

    if not customer.fullname:
        fullname = 'Pelanggan Setia Julo'
    else:
        fullname = customer.fullname

    action_attr = ConsentWithdrawal.MAPPING_ACTION_ATTRS["request"]
    subject = action_attr["email_subject"]
    gender_title = {'Pria': 'Bapak', 'Wanita': 'Ibu'}
    gender = gender_title.get(customer.gender, 'Bapak/Ibu')
    variable = {"title": gender, "fullname": fullname}

    template = get_template("consent_withdrawal/" + action_attr["email_template"] + ".html")
    html_content = template.render(variable)

    # Send the email with the rendered HTML content
    send_email_with_html(
        subject=subject,
        html_content=html_content,
        recipient_email=customer.email,
        sender_email=ConsentWithdrawal.EMAIL_CS,
        template_code=action_attr["email_template"],
    )
