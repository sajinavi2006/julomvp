from django.db import connection
from django.db.models import F, Prefetch
import logging

from juloserver.account.models import AccountLimit
from juloserver.integapiv1.models import EscrowPaymentMethod
from juloserver.julo.models import (
    Application,
    Loan,
    PaymentMethod,
    SphpTemplate,
)
from juloserver.julo.partners import PartnerConstant

from juloserver.partnership.constants import (
    PartnershipProductCategory,
    CARD_ID_METABASE_AXIATA_DISTRIBUTOR,
)
from juloserver.portal.object.bulk_upload.constants import MerchantFinancingCSVUploadPartner

from juloserver.portal.object.bulk_upload.scripts.retroload_mf_skrtp_new_template_existing_loan import (
    create_new_mf_skrtp,
)
from juloserver.sdk.models import AxiataCustomerData
from juloserver.metabase.clients import get_metabase_client
from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)
'''
    This logic is for create new Axiata MTL skrtp template for existing active loan
'''


def batching_loans(loan_ids):
    batch_size = 500
    counter = 0
    batch_loan_ids = []

    for loan_id in loan_ids:
        batch_loan_ids.append(loan_id)
        counter += 1

        if counter >= batch_size:
            loans = get_axiata_mtl_loans_info(loan_ids)

            counter = 0
            batch_loan_ids = []
            temp_errors = create_new_mf_skrtp(loans)

    if batch_loan_ids:
        loans = get_axiata_mtl_loans_info(loan_ids)
        temp_errors = create_new_mf_skrtp(loans)

    return temp_errors


def get_axiata_mtl_loans_info(loan_ids):
    loans = Loan.objects.select_related('customer', 'lender', 'product').filter(id__in=loan_ids)
    loans = loans.prefetch_related('payment_set')

    application_ids = [loan.application.id for loan in loans]

    applications = (
        Application.objects.filter(id__in=application_ids)
        .select_related('customer', 'account', 'partner')
        .prefetch_related(
            Prefetch('account__accountlimit_set', queryset=AccountLimit.objects.distinct()),
        )
    )

    application_dict = {application.customer_id: application for application in applications}

    julo_bank_account_numbers = [loan.julo_bank_account_number for loan in loans]

    payment_methods = PaymentMethod.objects.filter(virtual_account__in=julo_bank_account_numbers)

    payment_method_dict = {payment.virtual_account: payment for payment in payment_methods}

    unique_partner_names = set(
        application.partner.name for application in applications if application.partner
    )
    escrow_payment_methods = {}
    unique_product_templates = {}

    for partner_name in unique_partner_names:
        if partner_name == MerchantFinancingCSVUploadPartner.GAJIGESA:
            product_name = PartnershipProductCategory.EMPLOYEE_FINANCING
        else:
            product_name = PartnershipProductCategory.MERCHANT_FINANCING
        escrow_payment_method = (
            EscrowPaymentMethod.objects.filter(escrow_payment_gateway__owner__iexact=partner_name)
            .select_related('escrow_payment_gateway', 'escrow_payment_method_lookup')
            .last()
        )
        escrow_payment_methods[partner_name] = escrow_payment_method

        html_template = SphpTemplate.objects.filter(product_name=product_name).last()
        unique_product_templates[partner_name] = html_template

    axiata_customer_data_dict = {}
    axiata_distributor_data_dict = {}
    if PartnerConstant.AXIATA_PARTNER in unique_partner_names:
        axiata_customer_data = AxiataCustomerData.objects.filter(
            application_id__in=[application.id for application in applications]
        )
        for data in axiata_customer_data:
            axiata_customer_data_dict[data.application_id] = data

        distributor_ids = [data.distributor for data in axiata_customer_data]
        distributor_set = set(distributor_ids)

        try:
            metabase_client = get_metabase_client()
            response, error = metabase_client.get_metabase_data_json(
                CARD_ID_METABASE_AXIATA_DISTRIBUTOR
            )
            if error:
                raise Exception(error)

            for res in response:
                if str(res['distributor_id']) in distributor_set:
                    axiata_distributor_data_dict[res['axiata_distributor_id']] = res

        except Exception as e:
            sentry_client = get_julo_sentry_client()
            sentry_client.capture_exceptions()
            logger.exception(
                {
                    'module': 'get_axiata_mtl_loans_info',
                    'action': 'get_metabase_data_json',
                    'error': e,
                }
            )

            return

    detail_axiata_distributor_data = None
    for loan in loans:
        application = application_dict.get(loan.customer_id)
        if application:
            loan.application = application

            if application.partner:
                partner_name = application.partner.name
                if partner_name in unique_partner_names:
                    loan.html_template = unique_product_templates[partner_name]
                    loan.escrow_payment_method = escrow_payment_methods[partner_name]
                    loan.payment_method = payment_method_dict.get(loan.julo_bank_account_number)
                else:
                    loan.html_template = None
                    loan.escrow_payment_method = None
                    loan.payment_method = None

                if partner_name == PartnerConstant.AXIATA_PARTNER:
                    axiata_customer_data = axiata_customer_data_dict.get(application.id)
                    if axiata_customer_data:
                        for key, value in axiata_distributor_data_dict.items():
                            if value['distributor_id'] == int(axiata_customer_data.distributor):
                                detail_axiata_distributor_data = value
                        if detail_axiata_distributor_data:
                            axiata_distributor = {
                                'account_no': detail_axiata_distributor_data[
                                    'distributor_bank_account'
                                ],
                                'account_holder_name': detail_axiata_distributor_data[
                                    'distributor_bank_account_name'
                                ],
                                'bank_name': detail_axiata_distributor_data['bank_name'],
                            }
                            loan.axiata_distributor = axiata_distributor
                        else:
                            loan.axiata_distributor = None
                    else:
                        loan.axiata_distributor = None

            # Set last_payment
            loan.last_payment = loan.payment_set.last()

            account = application.account
            if account:
                loan.account_limit = account.accountlimit_set.last()
            else:
                loan.account_limit = None
        else:
            # if not have applications
            loan.applications = None
            loan.html_template = None
            loan.payment_method = None
            loan.last_payment = None

    return loans
