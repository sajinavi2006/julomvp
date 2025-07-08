from django.conf import settings
from django.db import transaction

from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import (
    BankAccountCategory,
    BankAccountDestination,
)
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.models import NameBankValidation
from juloserver.disbursement.services import ValidationProcess
from juloserver.julo.models import Bank, Customer, Partner


def name_bank_validation_for_mf_upload_patner(partner_name):
    partner = Partner.objects.get_or_none(name=partner_name)

    if not partner:
        print("Partner tidak ditemukan")
    elif partner.name_bank_validation:
        print('Name Bank Validation sudah dilakukan')

    with transaction.atomic():
        customer = Customer.objects.filter(user=partner.user).last()
        if not customer:
            print("Customer data untuk partner tidak ditemukan")
            return

        if settings.ENVIRONMENT == 'prod':
            name_in_bank = partner.partner_bank_account_name
        else:
            name_in_bank = 'prod only'

        partner_data = {
            'name_in_bank': name_in_bank,
            'account_number': partner.partner_bank_account_number,
            'bank_code': partner.partner_bank_name,
            'method': 'Xfers',
            'mobile_phone': '08111111111',
        }

        name_bank_validation = NameBankValidation.objects.create(
            bank_code=partner_data['bank_code'],
            account_number=partner_data['account_number'],
            name_in_bank=partner_data['name_in_bank'],
            mobile_phone=partner_data['mobile_phone'],
            method=partner_data['method'],
        )
        validation_process = ValidationProcess(name_bank_validation)
        validation_process.validate()
        name_bank_validation.refresh_from_db()
        if name_bank_validation.validation_status != NameBankValidationStatus.SUCCESS:
            raise Exception(
                'bank account not valid error : {}'.format(name_bank_validation.error_message)
            )
        partner_bank_account_category = BankAccountCategory.objects.filter(
            category=BankAccountCategoryConst.PARTNER
        ).last()
        bank = Bank.objects.filter(xfers_bank_code=partner_data['bank_code']).last()

        BankAccountDestination.objects.create(
            bank_account_category=partner_bank_account_category,
            customer=customer,
            bank=bank,
            account_number=partner_data['account_number'],
            name_bank_validation=name_bank_validation,
            description='{} bank account'.format(partner.name),
        )
        partner.name_bank_validation = name_bank_validation
        partner.save()

        print('success bank destination')
