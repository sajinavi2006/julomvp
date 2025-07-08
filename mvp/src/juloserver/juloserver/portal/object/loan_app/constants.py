
from core.functions import OrderList
from core.classes import ChoiceConstantBase


class ImageUploadType(ChoiceConstantBase):
    KTP_SELF                    = 'ktp_self'
    KK                          = 'kk'
    PAYSTUB                     = 'paystub'
    SELFIE                      = 'selfie'
    SIGNATURE                   = 'signature'
    BADGE                       = 'badge'
    LATEST_PAYMENT_PROOF        = 'latest_payment_proof'
    QRIS_SIGNATURE              = 'qris_signature'

    #TODO : will be hide after 2 weeks
    KTP_SPOUSE                  = 'ktp_spouse'
    ELECTRIC_BILL               = 'electric_bill'
    PHONE_BILL                  = 'phone_bill'
    WATER_BILL                  = 'water_bill'
    RENTAL_DOCUMENT             = 'rental_document'
    GOVERNMENT_DOCUMENT         = 'government_document'
    TAX_DOCUMENT                = 'tax_document'
    BUSINESS_INCOME_STATEMENT   = 'business_income_statement'
    BANK_STATEMENT              = 'bank_statement'
    DRIVERS_LICENSE             = 'drivers_license'

    COMPANY_PROOF = 'company_proof'
    ADDRESS_TRANSFER_CERTIFICATE = 'address_transfer_certificate'


class AppCheckType(ChoiceConstantBase):
    BINARY   = 1
    TEXT     = 2
    OPTIONS  = 3
    CURRENCY = 4

    @classmethod
    def ordering(cls, values):
        last_value = 'CURRENCY'
        ordered_values = sorted(values)
        if last_value in ordered_values:
            ordered_values.remove(last_value)
            ordered_values.append(last_value)
        return ordered_values
