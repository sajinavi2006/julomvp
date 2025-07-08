import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from datetime import datetime
from django.forms.models import model_to_dict
from typing import Tuple, Optional
from django.db.models.query import QuerySet

from django.db.models import Count, Max
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.models import (
    FeatureSetting,
    MobileFeatureSetting,
    PaymentMethodLookup,
    Application,
    Workflow,
    Customer,
)
from juloserver.julo.constants import (
    FeatureNameConst,
    PaymentMethodImpactedType,
    WorkflowConst,
    BNIVAConst,
)
from juloserver.sdk.constants import PARTNER_PEDE
from juloserver.paylater.models import Statement
from juloserver.payback.constants import GopayAccountStatusConst

from ..banks import BankCodes, BankManager
from juloserver.julo.models import (
    PaymentMethod, 
    VirtualAccountSuffix, 
    MandiriVirtualAccountSuffix,
    BniVirtualAccountSuffix,
)
from juloserver.payback.models import DokuVirtualAccountSuffix
from ..partners import PartnerConstant
from juloserver.julo.payment_methods import (
    PaymentMethodCodes,
    PaymentMethodManager,
    SecondaryMethodName,
    FaspayPaymentMethod,
    DokuPaymentMethod,
    OVOTokenizationPaymentMethod,
)
from ..statuses import LoanStatusCodes, PaymentStatusCodes
from ..utils import format_mobile_phone

from .constants import CustomerTypeConst
from juloserver.integapiv1.tasks import create_va_snap_bni_transaction
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.julo.payment_methods import PaymentMethod as PaymentMethodConst
from juloserver.account.models import Account
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.autodebet.constants import AutodebetVendorConst
from ...integapiv1.constants import SnapVendorChoices
from juloserver.ovo.services.account_services import (
    is_show_ovo_tokenization,
    is_show_ovo_payment_method,
)


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def get_application_primary_phone(application):
    if not application.mobile_phone_1:
        skiptrace = application.customer.skiptrace_set.filter(
            contact_source='mobile_phone_1',
            effectiveness__gte=-15).order_by('udate').last()
        if skiptrace:
            return skiptrace.phone_number.__str__()
        elif application.customer.phone and application.customer.phone != '':
            return application.customer.phone
        else:
            return
    return application.mobile_phone_1


def active_va(phone_number):
    customer_va = PaymentMethod.objects.filter(
        virtual_account__endswith=phone_number,
        is_shown=True)
    if customer_va:
        return True
    return False


def generate_customer_va(loan):
    customer = loan.application.customer
    customer_has_vas = PaymentMethod.objects.active_payment_method(customer)
    mobile_phone_1 = get_application_primary_phone(loan.application)
    is_active_va = False

    if mobile_phone_1:
        mobile_phone_1 = format_mobile_phone(mobile_phone_1)
        is_active_va = active_va(mobile_phone_1)

    if customer_has_vas and is_active_va:
        PaymentMethod.objects.filter(customer=customer) \
            .update(loan=loan)
        primary_payment_method = customer_has_vas.filter(is_primary=True).last()
        # prevent race condition for 150
        loan.update_safely(julo_bank_name=primary_payment_method.payment_method_name,
                           julo_bank_account_number=primary_payment_method.virtual_account)

        logger.info({
            'method': 'generate_customer_va',
            'loan': loan.id,
            'va': primary_payment_method.virtual_account,
            'customer': customer,
            'result': 'va created before'
        })

        return

    with transaction.atomic():
        va_suffix = None
        va_suffix_obj = None

        if not is_active_va:
            va_suffix = mobile_phone_1
            customer.update_safely(is_new_va=True)

        if not va_suffix:
            # get va_suffix
            va_suffix_obj = VirtualAccountSuffix.objects.select_for_update().filter(
                loan=None, line_of_credit=None, account=None).order_by('id').first()
            if not va_suffix_obj:
                raise Exception('no va suffix available')
            va_suffix_obj.loan = loan
            va_suffix_obj.save()
            va_suffix = va_suffix_obj.virtual_account_suffix
            va_suffix_random_number = va_suffix

        bank_name = loan.application.bank_name
        if "BCA" in bank_name:
            primary_bank_code = BankCodes.BCA
        elif "BRI" in bank_name:
            primary_bank_code = BankCodes.BRI
        else:
            primary_bank_code = BankCodes.PERMATA

        is_repayment_traffic_running = False
        partner = loan.application.partner

        if partner and partner.name in (PartnerConstant.ICARE_PARTNER, PartnerConstant.AXIATA_PARTNER):
            payment_methods = PaymentMethodManager.get_available_axiata_icare_payment_method()
        elif check_repayment_traffic_active() and \
                loan.application.product_line_code in ProductLineCodes.lended_by_jtp():
            customer_type = get_customer_type(bank_name)
            data = PaymentMethodManager.get_experiment_payment_method(customer_type)
            primary_bank_code, backup_bank_codes, payment_methods = data
            is_repayment_traffic_running = True
        else:
            payment_methods = PaymentMethodManager.get_available_payment_method(primary_bank_code)

        primary_payment_method = None

        if va_suffix_obj is None:
            va_suffix_obj = VirtualAccountSuffix.objects.select_for_update().filter(
                loan=None, line_of_credit=None, account=None).order_by('id').first()
            va_suffix_obj.loan = loan
            va_suffix_obj.save()
            va_suffix_random_number = va_suffix_obj.virtual_account_suffix

        secondary_methods = [sm.lower() for sm in SecondaryMethodName]
        payment_secondary_not_active = \
            [mf.lower() for mf in MobileFeatureSetting.objects.filter(feature_name__in=secondary_methods,
                                                                      is_active=False)
                .values_list('feature_name', flat=True)]

        for seq, payment_method in enumerate(payment_methods):
            sequence = seq + 1
            virtual_account = ""
            payment_code = payment_method.payment_code

            if payment_code:
                if payment_code[-1] == '0':
                    virtual_account = "".join([
                        payment_code,
                        va_suffix[1:]
                    ])
                else:
                    virtual_account = "".join([
                        payment_code,
                        va_suffix
                    ])

            # faspay didnt provide phone number payment code for permata/maybank
            # so use random va suffix
            if payment_method.code == BankCodes.MAYBANK or \
                    payment_method.code == BankCodes.PERMATA:
                if va_suffix_random_number is None:
                    continue

                virtual_account = "".join([payment_code,
                                           va_suffix_random_number])

            logger.info({
                'action': 'assigning_new_va',
                'bank_code': payment_method.code,
                'va': virtual_account,
                'customer': customer.id
            })

            is_shown = True
            bank_code = None
            is_primary = False

            if is_repayment_traffic_running:
                is_shown = True if payment_method.code not in backup_bank_codes else False
            elif payment_method.code == BankCodes.MAYBANK:
                is_shown = False
            else:
                is_shown = True

            if payment_method.type == 'bank':
                bank_code = payment_method.code

            if payment_method.code == primary_bank_code:
                is_primary = True
                loan.julo_bank_name = payment_method.name
                loan.julo_bank_account_number = virtual_account
                loan.save()

            if payment_method.name == 'Gopay' and loan.application.partner:
                is_shown = False
            elif loan.application.partner_name == PARTNER_PEDE and payment_method.name == 'Doku':
                is_shown = False

            if payment_method.name.lower() in payment_secondary_not_active:
                is_shown = False

            PaymentMethod.objects.create(
                payment_method_code=payment_code,
                payment_method_name=payment_method.name,
                bank_code=bank_code,
                customer=customer,
                is_shown=is_shown,
                is_primary=is_primary,
                loan=loan,
                virtual_account=virtual_account,
                sequence=sequence)

        partner = loan.application.partner

        if partner is not None:
            if partner.name == PartnerConstant.DOKU_PARTNER:
                doku_payment_method = PaymentMethodManager.get_or_none(
                    PaymentMethodCodes.DOKU)
                logger.info({
                    'action': 'assigning_payment_by_doku',
                    'va': settings.DOKU_ACCOUNT_ID,
                    'loan': loan.id
                })
                PaymentMethod.objects.create(
                    payment_method_code=doku_payment_method.code,
                    payment_method_name=doku_payment_method.name,
                    bank_code=None,
                    customer=customer,
                    is_shown=is_shown,
                    is_primary=False,
                    virtual_account=settings.DOKU_ACCOUNT_ID,
                    sequence=len(payment_methods) + 1)


def get_active_loan(payment_method):
    loan = None
    if payment_method.loan:
        loan = payment_method.loan
        if loan.status == LoanStatusCodes.SELL_OFF:
            loan = None
    elif payment_method.customer:
        customer = payment_method.customer
        loan = customer.loan_set.filter(
            loan_status__status_code__range=(
                LoanStatusCodes.CURRENT,
                LoanStatusCodes.RENEGOTIATED
            )).order_by('cdate').first()
    elif payment_method.customer_credit_limit:
        credit_limit = payment_method.customer_credit_limit
        loan = Statement.objects.filter(
            customer_credit_limit=credit_limit
        ).exclude(
            statement_status_id__in=PaymentStatusCodes.paylater_paid_status_codes()
        ).last()

    return loan


def get_payment_methods(loan):
    payment_methods = PaymentMethod.objects.filter(loan=loan, is_shown=True)
    if not payment_methods:
        payment_methods = PaymentMethod.objects.filter(
            customer=loan.customer, is_shown=True).order_by('sequence')

    return payment_methods


def get_customer_type(bank_name):
    """get customer type from bank name"""
    bank = BankManager.get_by_name_or_none(bank_name)
    if bank:
        for bnk in CustomerTypeConst.AVAILABLE_TYPE:
            if bnk in bank.xfers_bank_code.lower():
                return bnk
    return CustomerTypeConst.OTHER


def check_repayment_traffic_active():
    """check the feature is active"""
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.REPAYMENT_TRAFFIC_SETTING,
        is_active=True,
    ).exists()


def get_payment_method_type(
    payment_method: PaymentMethod, order_payment_methods_feature: FeatureSetting
):
    payment_method_type = None
    if payment_method.payment_method_name.lower() in order_payment_methods_feature.parameters.get(
        'bank_va_group'
    ):
        payment_method_type = 'Virtual Account'
    elif payment_method.payment_method_name.lower() in order_payment_methods_feature.parameters.get(
        'retail_group'
    ):
        payment_method_type = 'Retail'
    elif payment_method.payment_method_name.lower() in order_payment_methods_feature.parameters.get(
        'e_wallet_group'
    ):
        payment_method_type = 'E-Wallet'
    elif payment_method.payment_method_name.lower() in order_payment_methods_feature.parameters.get(
        'direct_debit_group'
    ):
        payment_method_type = 'Direct Debit'

    return payment_method_type


def aggregate_payment_methods(
    payment_methods,
    global_payment_methods,
    bank_name,
    partner=False,
    slimline_dict=False,
    is_new_version=False,
    version=1,
):
    customer = payment_methods.first().customer
    if customer:
        payment_methods = filter_payment_methods_by_lender(payment_methods, customer)
    global_payment_methods_dict = {}
    for payment_method in global_payment_methods:
        global_payment_methods_dict[payment_method.payment_method_name] = payment_method

    primary_payment_method = []
    bank_payment_method = []
    e_wallet_payment_method = []
    direct_debit_payment_method = []
    retail_payment_method = []
    autodebet_group = []
    new_repayment_channel_group = []
    ungrouped_payment_method = []
    disable_payment_method_list = get_disable_payment_methods()
    order_payment_methods_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ORDER_PAYMENT_METHODS_BY_GROUPS,
    ).last()
    payment_method_switch_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.PAYMENT_METHOD_SWITCH, is_active=True
    ).last()
    if payment_method_switch_fs:
        payment_method_vendors = {
            param['bank']: param['vendor']
            for param in payment_method_switch_fs.parameters['payment_method']
        }
    today_date = timezone.localtime(timezone.now()).date()
    end_date = order_payment_methods_feature.parameters.get('new_repayment_channel_group').get('end_date')
    if end_date:
        end_date = datetime.strptime(end_date, '%d-%m-%Y').date()
    latest_payment_method_exists = payment_methods.filter(is_latest_payment_method=True).exists()
    latest_bank_code = get_bank_code_by_bank_name(bank_name)
    for idx, payment_method in enumerate(payment_methods):
        payment_method_dict = model_to_dict(payment_method)
        if partner:
            payment_method_dict = payment_methods.values(
                'is_shown',
                'bank_code',
                'virtual_account',
                'is_primary',
                'is_shown',
                'payment_method_name',
                'is_latest_payment_method',
            )[idx]
        method_lookup = PaymentMethodLookup.objects.filter(
            name=payment_method.payment_method_name).first()
        if not method_lookup:
            continue
        global_payment_method = global_payment_methods_dict.get(payment_method.payment_method_name)
        if global_payment_method and is_global_payment_method_used(payment_method,
                                                                   global_payment_method):
            payment_method_dict['is_shown'] = global_payment_method.is_active

        if payment_method_switch_fs:
            if payment_method.payment_method_name in payment_method_vendors.keys():
                payment_method_dict['is_shown'] = True

        if not payment_method_dict['is_shown']:
            continue

        if not partner:
            payment_method_dict['bank_virtual_name'] = method_lookup.bank_virtual_name \
                                                       or method_lookup.name
            payment_method_dict['image_background_url'] = method_lookup.image_background_url
            payment_method_dict['image_logo_url'] = method_lookup.image_logo_url
            if is_new_version and method_lookup.image_logo_url_v2:
                payment_method_dict['image_logo_url'] = method_lookup.image_logo_url_v2

        payment_method_dict['is_enable'] = True
        if disable_payment_method_list:
            if payment_method.payment_method_name in disable_payment_method_list:
                payment_method_dict['is_enable'] = False

        if (
            payment_method_dict['is_latest_payment_method'] is None
            and not latest_payment_method_exists
        ):
            if latest_bank_code == payment_method_dict['bank_code']:
                payment_method_dict['is_latest_payment_method'] = True

        if is_new_version:
            payment_method_dict['type'] = get_payment_method_type(
                payment_method, order_payment_methods_feature
            )

            payment_method_dict['is_private'] = True
            non_private_methods = ['Bank MANDIRI', 'PERMATA Bank']
            if payment_method.payment_method_name in non_private_methods:
                payment_method_dict['is_private'] = False

            payment_method_faq_feature = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.PAYMENT_METHOD_FAQ_URL
            ).last()
            payment_method_dict['faq_url'] = \
                payment_method_faq_feature.parameters.get(payment_method.payment_method_name.lower())

        if slimline_dict:
            payment_method_dict.pop('loan', None)
            payment_method_dict.pop('line_of_credit', None)
            payment_method_dict.pop('edited_by', None)
            payment_method_dict.pop('is_affected', None)
            payment_method_dict.pop('payment_method_code', None)
            payment_method_dict.pop('is_preferred', None)
            payment_method_dict.pop('payment_method_name', None)
            payment_method_dict.pop('customer_credit_limit', None)

        payment_method_dict['is_show_new_badge'] = False
        if (end_date and today_date <= end_date and 
              payment_method.payment_method_name.lower() in \
              order_payment_methods_feature.parameters.get('new_repayment_channel_group').get('new_repayment_channel')):
            payment_method_dict['is_show_new_badge'] = True

        if payment_method.is_primary:
            primary_payment_method.append(payment_method_dict)
        elif payment_method.payment_method_name.lower() in order_payment_methods_feature.parameters.get('autodebet_group'):
            autodebet_group.append(payment_method_dict)
        elif payment_method.payment_method_name.lower() in order_payment_methods_feature.parameters.get('bank_va_group'):
            if payment_method_dict['is_show_new_badge']:
                new_repayment_channel_group.append(payment_method_dict)
            else:
                bank_payment_method.append(payment_method_dict)
        elif payment_method.payment_method_name.lower() in order_payment_methods_feature.parameters.get('retail_group'):
            retail_payment_method.append(payment_method_dict)
        elif (
            payment_method.payment_method_name.lower()
            in order_payment_methods_feature.parameters.get('e_wallet_group')
        ):
            if (
                payment_method.payment_method_name.lower()
                == OVOTokenizationPaymentMethod.name.lower()
            ):
                if version >= 5:
                    e_wallet_payment_method.append(payment_method_dict)
            else:
                e_wallet_payment_method.append(payment_method_dict)
        elif (
            payment_method.payment_method_name.lower()
            in order_payment_methods_feature.parameters.get('direct_debit_group')
        ):
            if version >= 5:
                direct_debit_payment_method.append(payment_method_dict)
        else:
            ungrouped_payment_method.append(payment_method_dict)

    list_method_lookups = (
        primary_payment_method
        + new_repayment_channel_group
        + bank_payment_method
        + retail_payment_method
        + direct_debit_payment_method
        + e_wallet_payment_method
        + autodebet_group
        + ungrouped_payment_method
    )

    return list_method_lookups


def is_global_payment_method_used(payment_method, global_payment_method):
    if global_payment_method.impacted_type is not None:
        if (global_payment_method.impacted_type == PaymentMethodImpactedType.PRIMARY_AND_BACKUP) \
                or (payment_method.is_primary and
                    global_payment_method.impacted_type == PaymentMethodImpactedType.PRIMARY) \
                or (not payment_method.is_primary and
                    global_payment_method.impacted_type == PaymentMethodImpactedType.BACKUP):
            if global_payment_method.is_priority or not payment_method.edited_by:
                return True
    else:
        if global_payment_method.is_priority or not payment_method.edited_by:
            return True

    return False


def generate_specific_suffix_payment_method(
    payment_code: str,
    virtual_account: str,
    va_suffix_random_number: str,
    payment_method: PaymentMethodConst,
    account: Account,
) -> Tuple[str, bool]:
    """
    This method is use to consume suffix from specific table
    because some payment method can't use phone number
    (phone number length too long).
    """

    is_include_bni_payment_method = False

    if payment_method.payment_code in DokuPaymentMethod:
        with transaction.atomic(using='repayment_db'):
            doku_va_suffix_obj = (
                DokuVirtualAccountSuffix.objects.select_for_update()
                .filter(Q(account_id=None) | Q(account_id=account.id))
                .order_by('id')
                .first()
            )
            if doku_va_suffix_obj:
                doku_va_suffix_obj.account_id = account.id
                doku_va_suffix_obj.save()
                doku_va_suffix = doku_va_suffix_obj.virtual_account_suffix

                virtual_account = "".join([payment_method.payment_code, doku_va_suffix])
    else:
        # faspay didnt provide phone number payment code for permata/maybank
        # so use random va suffix
        if payment_method.code == BankCodes.MAYBANK or payment_method.code == BankCodes.PERMATA:
            if va_suffix_random_number:
                virtual_account = "".join([payment_method.payment_code, va_suffix_random_number])

        # Faspay prefix for mandiri is long(8 digits) so can't use phone number as va_suffix
        # so using separate mandiri_va_suffix
        if payment_method.code == BankCodes.MANDIRI:
            mandiri_va_suffix_obj = (
                MandiriVirtualAccountSuffix.objects.select_for_update()
                .filter(account=None)
                .order_by('id')
                .first()
            )
            if mandiri_va_suffix_obj:
                mandiri_va_suffix_obj.account = account
                mandiri_va_suffix_obj.save()
                mandiri_va_suffix = mandiri_va_suffix_obj.mandiri_virtual_account_suffix

                virtual_account = "".join([payment_method.payment_code, mandiri_va_suffix])

        # Faspay prefix for BNI is too long(10 digits) so can't use phone number as va_suffix
        # so using separate bni_va_suffix(6 digits)
        if payment_method.code == BankCodes.BNI:
            with transaction.atomic(using='repayment_db'):
                bni_va_suffix_obj = (
                    BniVirtualAccountSuffix.objects.select_for_update()
                    .filter(account_id=None)
                    .order_by('id')
                    .first()
                )

                if bni_va_suffix_obj:
                    bni_va_suffix_obj.account_id = account.id
                    bni_va_suffix_obj.save()
                    bni_va_suffix = bni_va_suffix_obj.bni_virtual_account_suffix

                    # Grouping VA suffix and prefix based on its value
                    if int(bni_va_suffix) / 1000000 >= 1:
                        payment_code = PaymentMethodCodes.BNI_V2
                        bni_va_suffix = str(int(bni_va_suffix) % 1000000).zfill(6)

                    virtual_account = "".join([payment_code, bni_va_suffix])
                    is_include_bni_payment_method = True

    return payment_code, virtual_account, is_include_bni_payment_method


def generate_customer_va_for_julo_one(application):
    account = application.account
    customer = account.customer
    customer_has_vas = PaymentMethod.objects.active_payment_method(customer)
    mobile_phone_1 = get_application_primary_phone(application)
    is_active_va = False

    if mobile_phone_1:
        mobile_phone_1 = format_mobile_phone(mobile_phone_1)
        if application.is_merchant_flow():
            mobile_phone_1 = mobile_phone_1[0] + '1' + mobile_phone_1[2:]
        is_active_va = active_va(mobile_phone_1)

    if customer_has_vas and is_active_va:
        primary_payment_method = customer_has_vas.filter(is_primary=True).last() or customer_has_vas.last()
        # update previous payment method with new loan
        for payment_method in customer_has_vas:
            loan = payment_method.loan
            if loan and loan.loan_status_id < LoanStatusCodes.CURRENT:
                payment_method.update_safely(loan=None)

        logger.info({
            'method': 'generate_customer_va_for_julo_one',
            'va': primary_payment_method.virtual_account,
            'customer': customer,
            'result': 'va created before'
        })

        return

    is_include_bni_payment_method = False
    with transaction.atomic(), transaction.atomic(using='repayment_db'):
        va_suffix = None
        va_suffix_obj = None
        payment_method_lookup_codes = []
        if not is_active_va:
            va_suffix = mobile_phone_1
            customer.update_safely(is_new_va=True)

        if not va_suffix:
            # get va_suffix
            va_suffix_obj = VirtualAccountSuffix.objects.select_for_update().filter(
                loan=None, line_of_credit=None, account=None).order_by('id').first()
            if not va_suffix_obj:
                raise Exception('no va suffix available')
            va_suffix_obj.account = account
            va_suffix_obj.save()
            va_suffix = va_suffix_obj.virtual_account_suffix
            va_suffix_random_number = va_suffix

        bank_name = application.bank_name
        if application.is_merchant_flow():
            bank_name = application.merchant.distributor.bank_name
        if "BCA" in bank_name:
            primary_bank_code = BankCodes.BCA
        elif "BRI" in bank_name:
            primary_bank_code = BankCodes.BRI
        elif "MANDIRI" in bank_name:
            primary_bank_code = BankCodes.MANDIRI
        elif 'BNI' in bank_name:
            primary_bank_code = BankCodes.BNI
        elif 'CIMB' in bank_name:
            primary_bank_code = BankCodes.CIMB_NIAGA
        else:
            primary_bank_code = BankCodes.PERMATA

        is_repayment_traffic_running = False
        if check_repayment_traffic_active() and \
                (application.product_line_code in ProductLineCodes.lended_by_jtp() or \
                        application.product_line_code == ProductLineCodes.JULO_STARTER):
            customer_type = get_customer_type(bank_name)
            if primary_bank_code == BankCodes.BNI:
                """ This code block is to verify and block the BNI VA generation by changing the customer_type to other bank customer
                    and triggering the notification email, if the generation limit is already reached """
                #importing here due to import error
                from juloserver.julo.tasks import send_email_bni_va_generation_limit_alert
                bni_eligible_product_line_list = [ProductLineCodes.J1, ProductLineCodes.JULO_STARTER]
                bni_va_count = PaymentMethod.objects.filter(payment_method_name='Bank BNI').count()
                if bni_va_count in BNIVAConst.COUNT_LIST:
                    send_email_bni_va_generation_limit_alert.delay(bni_va_count)
                if not application.product_line_code in bni_eligible_product_line_list or \
                        is_block_bni_va_auto_generation() or bni_va_count >= BNIVAConst.MAX_LIMIT:
                    customer_type = CustomerTypeConst.OTHER

            data = PaymentMethodManager.get_experiment_payment_method(customer_type)
            primary_bank_code, backup_bank_codes, payment_methods = data
            is_repayment_traffic_running = True
        else:
            if primary_bank_code == BankCodes.BNI:
                if not application.product_line_code in [ProductLineCodes.J1, ProductLineCodes.JULO_STARTER]:
                    primary_bank_code = BankCodes.PERMATA

            if application.is_merchant_flow():
                payment_methods = PaymentMethodManager.get_all_payment_methods()
            else:
                payment_methods = PaymentMethodManager.get_available_payment_method(primary_bank_code)

        primary_payment_method = None
        if va_suffix_obj is None:
            va_suffix_obj = VirtualAccountSuffix.objects.select_for_update().filter(
                loan=None, line_of_credit=None, account=None).order_by('id').first()
            va_suffix_obj.account = account
            va_suffix_obj.save()
            va_suffix_random_number = va_suffix_obj.virtual_account_suffix

        secondary_methods = [sm.lower() for sm in SecondaryMethodName]
        payment_secondary_not_active = \
            [mf.lower() for mf in MobileFeatureSetting.objects.filter(feature_name__in=secondary_methods,
                                                                      is_active=False)
                .values_list('feature_name', flat=True)]
        # set is shown False for prevent 2 display payment methods
        PaymentMethod.objects.filter(customer=customer).update(
            is_primary=False, is_shown=False
        )

        if application.is_merchant_flow():
            payment_method_lookups = PaymentMethodLookup.objects.filter(is_shown_mf=True)
            if payment_method_lookups:
                payment_method_lookup_codes = {payment_method_lookup.code
                                               for payment_method_lookup in payment_method_lookups}
                if settings.FASPAY_PREFIX_OLD_ALFAMART in payment_method_lookup_codes:
                    payment_method_lookup_codes.add(PaymentMethodCodes.ALFAMART)

                if PaymentMethodCodes.OLD_INDOMARET in payment_method_lookup_codes:
                    payment_method_lookup_codes.add(PaymentMethodCodes.INDOMARET)

        for seq, payment_method in enumerate(payment_methods):
            sequence = seq + 1
            virtual_account = ""
            payment_code = payment_method.payment_code
            vendor = payment_method.vendor

            if payment_code:
                if payment_code[-1] == '0' and payment_code != PaymentMethodCodes.DANA_BILLER:
                    virtual_account = "".join([
                        payment_code,
                        va_suffix[1:]
                    ])
                else:
                    virtual_account = "".join([
                        payment_code,
                        va_suffix
                    ])

            (
                payment_code,
                virtual_account,
                is_include_bni_payment_method,
            ) = generate_specific_suffix_payment_method(
                payment_code,
                virtual_account,
                va_suffix_random_number,
                payment_method,
                account,
            )

            logger.info({
                'action': 'assigning_new_va',
                'bank_code': payment_method.code,
                'va': virtual_account,
                'customer': customer.id
            })

            is_shown = True
            bank_code = None
            is_primary = False
            if is_repayment_traffic_running:
                is_shown = True
            elif payment_method.code == BankCodes.MAYBANK:
                is_shown = False

            if payment_method.code == PaymentMethodCodes.DANA_BILLER:
                is_shown = False

            if payment_method.type == 'bank':
                bank_code = payment_method.code

            if payment_method.code == primary_bank_code:
                is_primary = True

            if payment_method.name.lower() in payment_secondary_not_active:
                is_shown = False

            if payment_method.payment_code in FaspayPaymentMethod:
                is_shown = False
                is_primary = False

            PaymentMethod.objects.create(
                payment_method_code=payment_code,
                payment_method_name=payment_method.name,
                bank_code=bank_code,
                customer=customer,
                is_shown=is_shown,
                is_primary=is_primary,
                virtual_account=virtual_account,
                sequence=sequence,
                vendor=vendor,
            )

    if application.is_merchant_flow():
        payment_methods = PaymentMethod.objects.filter(customer=customer, is_primary=False)
        payment_methods.update(is_shown=False)
        if payment_method_lookup_codes:
            payment_methods.filter(bank_code__in=payment_method_lookup_codes).update(is_shown=True)
            payment_methods.filter(payment_method_code__in=payment_method_lookup_codes).update(is_shown=True)
    
    # Post to Faspay SNAP if BNI payment method is created
    if is_include_bni_payment_method:
        execute_after_transaction_safely(
            lambda: create_va_snap_bni_transaction.delay(
                account.id, 'julo.services2.payment_method.generate_customer_va_for_julo_one'
            )
        )

def search_payments_base_on_virtual_account(virtual_account_number):
    # grouping payment method base on prefix
    payment_methods = PaymentMethod.objects.filter(
        is_shown=True
    ).values('payment_method_code').annotate(
        dcount=Count('payment_method_code')
    ).order_by('-dcount')
    for payment_method in payment_methods:
        prefix = payment_method['payment_method_code']
        if virtual_account_number[:len(prefix)] == prefix:
            return True, PaymentMethod.objects.filter(
                is_shown=True, virtual_account=virtual_account_number
            ).values_list('customer_id', flat=True)

    return False, []


def update_mf_payment_method_is_shown_mf_flag(code, is_shown_mf):
    workflow = Workflow.objects.get(name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW)
    if workflow:
        applications = Application.objects.select_related("customer").filter(workflow=workflow)
        if code == settings.FASPAY_PREFIX_OLD_ALFAMART:
            code = PaymentMethodCodes.ALFAMART
        elif code == PaymentMethodCodes.OLD_INDOMARET:
            code = PaymentMethodCodes.INDOMARET

        if applications:
            for application in applications:
                if code:
                    # check whether code is bank code
                    if len(code) == 3:
                        payment_method = PaymentMethod.objects.filter(customer=application.customer,
                                                                      is_primary=False,
                                                                      bank_code=code)
                        payment_method.update(is_shown=is_shown_mf)
                    elif len(code) > 3:
                        payment_method = PaymentMethod.objects.filter(customer=application.customer,
                                                                      is_primary=False,
                                                                      payment_method_code=code)
                        payment_method.update(is_shown=is_shown_mf)

        return True
    return False


def is_hide_mandiri_payment_method():
    """check the feature is active"""
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MANDIRI_PAYMENT_METHOD_HIDE,
        is_active=True,
    ).exists()


def create_or_update_gopay_payment_method(customer, gopay_account_link_status, phone=None, is_get_payment_method=False):
    if not phone and not gopay_account_link_status:
        return

    new_gopay_payment_method = PaymentMethod.objects.filter(
        customer=customer,
        payment_method_code=PaymentMethodCodes.GOPAY_TOKENIZATION,
        payment_method_name='GoPay Tokenization'
    ).last()

    old_gopay_payment_method = PaymentMethod.objects.filter(
            customer=customer,
            payment_method_code=PaymentMethodCodes.GOPAY,
            payment_method_name='Gopay'
    ).last()

    if new_gopay_payment_method:
        gopay_account_status_list = [
            GopayAccountStatusConst.PENDING,
            GopayAccountStatusConst.DISABLED,
            GopayAccountStatusConst.EXPIRED
        ]

        if gopay_account_link_status == GopayAccountStatusConst.ENABLED:
            if not new_gopay_payment_method.is_shown:
                new_gopay_payment_method.update_safely(is_shown=True)
                if old_gopay_payment_method and old_gopay_payment_method.is_shown:
                    old_gopay_payment_method.update_safely(is_shown=False)
            
            if not new_gopay_payment_method.sequence:
                if old_gopay_payment_method and old_gopay_payment_method.sequence:
                    new_gopay_payment_method.update_safely(
                        sequence=old_gopay_payment_method.sequence
                    )
                    old_gopay_payment_method.update_safely(sequence=None)

            if old_gopay_payment_method and old_gopay_payment_method.is_latest_payment_method:
                new_gopay_payment_method.update_safely(is_latest_payment_method=True)
                old_gopay_payment_method.update_safely(is_latest_payment_method=False)

        elif gopay_account_link_status in gopay_account_status_list:
            if new_gopay_payment_method.is_shown:
                new_gopay_payment_method.update_safely(is_shown=False)
                if old_gopay_payment_method and not old_gopay_payment_method.is_shown:
                    old_gopay_payment_method.update_safely(is_shown=True)

            if new_gopay_payment_method.sequence:
                if old_gopay_payment_method and not old_gopay_payment_method.sequence:
                    old_gopay_payment_method.update_safely(
                        sequence=new_gopay_payment_method.sequence
                    )
                    new_gopay_payment_method.update_safely(sequence=None)

            if new_gopay_payment_method.is_latest_payment_method:
                new_gopay_payment_method.update_safely(is_latest_payment_method=False)
                if old_gopay_payment_method:
                    old_gopay_payment_method.update_safely(is_latest_payment_method=True)

    elif not new_gopay_payment_method and phone:
        va_suffix = format_mobile_phone(phone)
        virtual_account = "".join([
            PaymentMethodCodes.GOPAY_TOKENIZATION,
            va_suffix
        ])

        payment_method = {
            'payment_method_code': PaymentMethodCodes.GOPAY_TOKENIZATION,
            'payment_method_name': 'GoPay Tokenization',
            'customer': customer,
            'virtual_account': virtual_account,
            'sequence': None,
            'is_shown': False,
            'is_primary': False,
        }

        if old_gopay_payment_method and old_gopay_payment_method.is_primary:
            payment_method['is_primary'] = True

        if gopay_account_link_status == GopayAccountStatusConst.ENABLED:
            payment_method['is_shown'] = True
            if old_gopay_payment_method:
                if old_gopay_payment_method.is_shown:
                    old_gopay_payment_method.update_safely(is_shown=False)
                if old_gopay_payment_method.sequence:
                    payment_method['sequence'] = old_gopay_payment_method.sequence
                    old_gopay_payment_method.update_safely(sequence=None)
                if old_gopay_payment_method.is_latest_payment_method:
                    old_gopay_payment_method.update_safely(is_latest_payment_method=False)
                    payment_method['is_latest_payment_method'] = True

        PaymentMethod.objects.create(**payment_method)

    if is_get_payment_method:
        return new_gopay_payment_method


def is_block_bni_va_auto_generation():
    """check feature is active"""
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BLOCK_BNI_VA_AUTO_GENERATION,
        is_active=True,
    ).exists()


def get_disable_payment_methods():
    disable_payment_method_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DISABLE_PAYMENT_METHOD,
        is_active=True
    ).last()

    if disable_payment_method_feature and disable_payment_method_feature.parameters:
        start_date_time = disable_payment_method_feature.parameters.get('disable_start_date_time')
        end_date_time = disable_payment_method_feature.parameters.get('disable_end_date_time')
        payment_method_name_list = disable_payment_method_feature.parameters.get('payment_method_name')

        if start_date_time and end_date_time and payment_method_name_list:
            today = datetime.strptime(datetime.strftime(timezone.localtime(timezone.now()), '%d/%m/%y %H:%M'), '%d/%m/%y %H:%M')
            start_date_time = datetime.strptime(start_date_time, '%d-%m-%Y %H:%M')
            end_date_time = datetime.strptime(end_date_time, '%d-%m-%Y %H:%M')
            if start_date_time <= today <= end_date_time:
                return payment_method_name_list

    return []


def get_bank_code_by_bank_name(bank_name: str) -> str:
    bank_code = BankCodes.PERMATA
    if not isinstance(bank_name, str):
        return bank_code
    if "BCA" in bank_name:
        bank_code = BankCodes.BCA
    elif "BRI" in bank_name:
        bank_code = BankCodes.BRI
    elif "MANDIRI" in bank_name:
        bank_code = BankCodes.MANDIRI
    elif 'BNI' in bank_name:
        bank_code = BankCodes.BNI
    return bank_code


def filter_payment_methods_by_lender(payment_methods: QuerySet, customer: Customer) -> QuerySet:
    try:
        account = customer.account_set.last()
        if not account:
            return payment_methods
        if payment_methods.count() == 0:
            return payment_methods
        fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.HIDE_PAYMENT_METHODS_BY_LENDER,
            is_active=True,
        ).last()
        if not fs:
            return payment_methods
        hide_payment_methods_by_lender_id = {}
        for hide_payment_method in fs.parameters:
            hide_payment_methods_by_lender_id[
                int(hide_payment_method['lender_id'])
            ] = hide_payment_method['payment_method_codes']
        if not hide_payment_methods_by_lender_id:
            return payment_methods
        lender_ids = list(
            account.loan_set.filter(
                loan_status_id__gte=LoanStatusCodes.CURRENT,
                loan_status_id__lt=LoanStatusCodes.PAID_OFF,
                lender_id__in=hide_payment_methods_by_lender_id.keys(),
            ).values_list('lender_id', flat=True)
        )
        if not lender_ids:
            return payment_methods
        hide_payment_method_codes = set()
        for lender_id in lender_ids:
            if lender_id in hide_payment_methods_by_lender_id:
                hide_payment_method_codes.update(hide_payment_methods_by_lender_id.get(lender_id))
        payment_methods = payment_methods.exclude(payment_method_code__in=hide_payment_method_codes)
        return payment_methods
    except Exception as e:
        sentry_client.captureException()
        logger.error(
            {
                'method': 'juloserver.julo.services2.payment_method.filter_payment_methods_by_lender',
                'error': str(e),
                'customer': customer.id,
            }
        )
        return payment_methods


def get_excluded_payment_method_whitelist(account):
    # circular import
    from juloserver.dana_linking.services import is_show_dana_linking
    from juloserver.oneklik_bca.services import is_show_oneklik_bca
    from juloserver.payback.services.gopay import GopayServices

    excluded_payment_method_codes = []
    if not account:
        return []
    if not is_show_ovo_payment_method(account):
        excluded_payment_method_codes.append(PaymentMethodCodes.OVO)

    if not is_show_ovo_tokenization(account.last_application.id):
        excluded_payment_method_codes.append(PaymentMethodCodes.OVO_TOKENIZATION)

    if not is_show_dana_linking(account.last_application.id):
        excluded_payment_method_codes.append(PaymentMethodCodes.DANA)

    if not is_show_oneklik_bca(account.last_application.id):
        excluded_payment_method_codes.append(PaymentMethodCodes.ONEKLIK_BCA)

    if not GopayServices.is_show_gopay_account_linking(account.id):
        excluded_payment_method_codes.append(PaymentMethodCodes.GOPAY_TOKENIZATION)

    return excluded_payment_method_codes


def get_main_payment_method(customer: Customer) -> Optional[PaymentMethod]:
    try:
        excluded_payment_method_codes = get_excluded_payment_method_whitelist(customer.account)
        payment_method_qs = customer.paymentmethod_set.filter(is_shown=True).exclude(
            payment_method_code__in=excluded_payment_method_codes
        )
        payment_method_qs = filter_payment_methods_by_lender(payment_method_qs, customer)
        payment_method = payment_method_qs.filter(is_latest_payment_method=True).first()
        if payment_method:
            return payment_method
        payment_method = payment_method_qs.filter(is_primary=True).first()
        if payment_method:
            return payment_method
        application = customer.application_set.last()
        if application:
            bank_code = get_bank_code_by_bank_name(application.bank_name)
            payment_method = (
                payment_method_qs.filter(bank_code=bank_code)
                .exclude(payment_method_code__in=AutodebetVendorConst.get_all_payment_method_code())
                .first()
            )
        if payment_method:
            return payment_method
        payment_method = (
            payment_method_qs.filter(
                bank_code__in={
                    BankCodes.BCA,
                    BankCodes.BRI,
                    BankCodes.MANDIRI,
                    BankCodes.BNI,
                    BankCodes.CIMB_NIAGA,
                    BankCodes.PERMATA,
                }
            )
            .exclude(payment_method_code__in=AutodebetVendorConst.get_all_payment_method_code())
            .order_by('sequence')
            .first()
        )
        return payment_method
    except Exception as e:
        sentry_client.captureException()
        logger.error(
            {
                'method': 'juloserver.julo.services2.payment_method.get_main_payment_method',
                'error': str(e),
                'customer': customer.id,
            }
        )
