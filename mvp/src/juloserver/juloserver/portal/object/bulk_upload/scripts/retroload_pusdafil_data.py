"""
please make the data strucutre be like (need to be unique for each customer
(because the key is nik)
data = {
    '1005180907992200':{
        'monthly_income': '500000',
        'kin_name': 'kin_name',
        'kin_mobile_phone': 'kin_mobile_phone',
        'home_status': 'home_status',
    }
}

"""
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.sdk.models import AxiataCustomerData
from django.utils import timezone
from django_bulk_update.helper import bulk_update


def retroload_pusdafil_data_axiata(data):
    list_of_nik = []
    for nik in data:
        list_of_nik.append(nik)

    axiata_customer_datas = AxiataCustomerData.objects.select_related(
        'application__customer', 'application__loan'
    ).filter(ktp__in=list_of_nik)
    update_acd_data = []
    update_applications = []
    update_customers = []
    update_customer_ids = set()
    error_ktp = []
    for acd in axiata_customer_datas.iterator():
        acd_data = data[acd.ktp]
        if acd_data.get('kin_name') is None:
            print('{} has kin_name is null', format(acd.ktp))
            error_ktp.append(acd.ktp)
            continue
        if acd_data.get('kin_mobile_phone') is None:
            print('{} has kin_mobile_phone is null', format(acd.ktp))
            error_ktp.append(acd.ktp)
            continue
        if acd_data.get('monthly_income') is None:
            print('{} has monthly_income is null', format(acd.ktp))
            error_ktp.append(acd.ktp)
            continue
        if acd_data.get('home_status') is None:
            print('{} has home_status is null', format(acd.ktp))
            error_ktp.append(acd.ktp)
            continue

        application = acd.application
        if not application:
            continue

        # skipping for not active loan
        loan = application.loan
        if not LoanStatusCodes.CURRENT <= loan.status < LoanStatusCodes.PAID_OFF:
            continue

        acd.kin_name = acd_data.get('kin_name')
        acd.kin_mobile_phone = acd_data.get('kin_mobile_phone')
        acd.income = int(acd_data.get('monthly_income'))
        acd.home_status = acd_data.get('home_status')
        acd.udate = timezone.localtime(timezone.now())
        acd.user_type = 'perorangan'
        update_acd_data.append(acd)

        application.kin_name = acd_data.get('kin_name')
        application.kin_mobile_phone = acd_data.get('kin_mobile_phone')
        application.home_status = acd_data.get('home_status')
        application.udate = timezone.localtime(timezone.now())
        update_applications.append(application)

        customer = application.customer
        # skipping if the customer id already updated
        if customer.id in update_customer_ids:
            continue
        customer.kin_name = acd_data.get('kin_name')
        customer.kin_mobile_phone = acd_data.get('kin_mobile_phone')
        customer.udate = timezone.localtime(timezone.now())
        update_customers.append(customer)
        update_customer_ids.add(customer.id)

    bulk_update(
        update_acd_data,
        update_fields=[
            'kin_name',
            'kin_mobile_phone',
            'income',
            'home_status',
            'udate',
            'user_type',
        ],
        batch_size=100,
    )
    bulk_update(
        update_applications,
        update_fields=['kin_name', 'kin_mobile_phone', 'monthly_income', 'home_status', 'udate'],
        batch_size=100,
    )
    bulk_update(
        update_customers,
        update_fields=['kin_name', 'kin_mobile_phone', 'monthly_income', 'udate'],
        batch_size=100,
    )
    print('successfully upddated for pusdafil data')
