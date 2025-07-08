import datetime

from juloserver.julo.constants import SPHPConst
from juloserver.julo.utils import display_rupiah
from juloserver.julo.models import Application, SphpTemplate


def get_sphp(application_id, customer):
    application_object = Application.objects.filter(pk=application_id, customer=customer).first()
    loan = application_object.loan
    text = SphpTemplate.objects.filter(product_name="laku6").get()
    now = datetime.datetime.now()
    date_today = now.strftime("%Y-%m-%d")
    data = dict()
    data['date_today'] = date_today
    data['full_address'] = application_object.complete_addresses
    data['bank_name'] = loan.julo_bank_name
    data['bank_code'] = ""
    data['dob'] = application_object.dob
    data['ktp'] = application_object.ktp
    data['mobile_phone_1'] = application_object.mobile_phone_1
    data['fullname'] = application_object.fullname
    data['application_xid'] = application_object.application_xid
    data['loan_amount'] = display_rupiah(loan.loan_amount)
    data['lender_agreement_number'] = SPHPConst.AGREEMENT_NUMBER,
    data['late_fee_amount'] = display_rupiah(loan.max_total_late_fee_amount)
    data['VA_number'] = loan.julo_bank_account_number
    data['provision_fee_amount'] = display_rupiah(loan.provision_fee())
    data['interest_rate'] = '{}%'.format(loan.interest_percent_monthly()),
    return text.sphp_template.format(**data)
