import juloserver.merchant_financing.services as mf_services
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.julo.models import Partner, Bank
from juloserver.partnership.models import PartnershipDistributor
from django.db import transaction

"""
referencing validate_and_insert_distributor_data
sample data 
data = [
    {
        'distributor_id':'1001',
        'distributor_name':'PTÂ CatalistÂ Integra Prima Sukses',
        'distributor_bank_account':'4943062121',
        'distributor_bank_account_name':'PTÂ CatalistÂ Integra Prima Sukses',
        'bank_code':'14',
        'bank_name':'BANK CENTRAL ASIA, Tbk (BCA)'
    },
]
"""


@transaction.atomic
def bulk_upload_axiata_distributor(data):
    error_distributor = {}
    partnership_distributors_list = {}
    partner = Partner.objects.filter(name='axiata').last()
    for item in data:
        is_valid_bank = False
        bank = None
        distributor_code = item.get('distributor_id')
        distributor_name = item.get('distributor_name')
        distributor_bank_name = item.get('distributor_bank_account_name')
        bank_account = item.get('distributor_bank_account')
        bank_name = item.get('bank_name')
        bank_code = item.get('bank_code')

        if not distributor_code:
            error_distributor[distributor_name] = "distributor code not found"
            continue

        if distributor_code and not distributor_code.isdigit():
            error_distributor[distributor_code] = 'distributor_code: harus menggunakan angka'
            continue
        else:
            is_distributor_exists = PartnershipDistributor.objects.filter(
                distributor_id=distributor_code, is_deleted=False, partner_id=partner.id
            ).exists()
            if is_distributor_exists:
                error_distributor[distributor_code] = 'distributor_code: telah terdaftar'
                continue

        if not distributor_name:
            error_distributor[distributor_code] = "distributor_name: tidak boleh kosong"
            continue

        if not distributor_bank_name:
            error_distributor[distributor_code] = "distributor_bank_name: tidak boleh kosong"
            continue

        if partnership_distributors_list.get(distributor_code):
            error_distributor[distributor_code] = "distributor_code already registered"
            continue

        if distributor_bank_name:
            bank = Bank.objects.values('xfers_bank_code').filter(bank_name=bank_name).first()
            if not bank:
                error_distributor[
                    distributor_code
                ] = "distributor_bank_name: nama bank tidak sesuai"
                continue
            is_valid_bank = True

        if not bank_account:
            error_distributor[distributor_code] = 'distributor_bank_account: tidak boleh kosong'
            continue

        if bank_account and not bank_account.isdigit():
            error_distributor[
                distributor_code
            ] = 'distributor_bank_account: format tidak sesuai, harus mengggunakan angka'
            continue

        if not bank_name:
            error_distributor[distributor_code] = 'bank_name: tidak boleh kosong'
            continue

        if not bank_code:
            error_distributor[distributor_code] = 'bank_code: tidak boleh kosong'

        if bank_code and not bank_code.isdigit():
            error_distributor[
                distributor_code
            ] = 'bank_code: format tidak sesuai, harus mengggunakan angka'

        if (
            distributor_code
            and distributor_code.isdigit()
            and bank_account
            and bank_account.isdigit()
            and distributor_bank_name
            and is_valid_bank
            and bank
        ):
            bank_account_services = mf_services.BankAccount()
            response = bank_account_services.inquiry_bank_account(
                bank_code=bank['xfers_bank_code'],
                bank_account_number=bank_account,
                phone_number="08111111111",
                name_in_bank=distributor_bank_name,
            )
            if response['status'] != NameBankValidationStatus.SUCCESS:
                error_distributor[distributor_code] = 'bank_name: {}'.format(response['reason'])
            elif response['validated_name'].lower() != distributor_bank_name.lower():
                error_distributor[
                    distributor_code
                ] = 'bank_name: nama pemilik rekening tidak sesuai'
            else:
                partnership_distributor_data = {
                    'distributor_id': distributor_code,
                    'distributor_name': distributor_name,
                    'distributor_bank_account_number': bank_account,
                    'distributor_bank_account_name': distributor_bank_name,
                    'bank_code': bank_code,
                    'bank_name': bank_name,
                    'partner': partner,
                    'is_deleted': False,
                }
                partnership_distributors_list[distributor_code] = partnership_distributor_data

    partnership_distributors = []
    for distributor_code in partnership_distributors_list:
        partnership_distributors.append(
            PartnershipDistributor(**partnership_distributors_list.get(distributor_code))
        )

    PartnershipDistributor.objects.bulk_create(partnership_distributors)

    return error_distributor
