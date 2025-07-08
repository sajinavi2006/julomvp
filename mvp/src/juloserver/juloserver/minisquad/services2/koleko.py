import os
import csv
import math
from datetime import timedelta

from django.utils import timezone
from django.conf import settings

from juloserver.grab.constants import SPLIT_DATA_FOR_KOLEKO_PER
from juloserver.julo.models import (
    PaymentMethod,
    Payment,
    Loan,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import (
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.utils import format_mobile_phone
from juloserver.minisquad.constants import RedisKey


def get_oldest_grab_payment_ids():
    redis_client = get_redis_client()
    cached_oldest_payment_ids = redis_client.get_list(RedisKey.GRAB_OLDEST_PAYMENT_IDS)
    if not cached_oldest_payment_ids:
        loans = Loan.objects.filter(
            loan_status_id__gte=LoanStatusCodes.CURRENT,
            loan_status_id__lt=LoanStatusCodes.RENEGOTIATED,
            product__product_line_id=ProductLineCodes.GRAB
        ).values_list('id', flat=True)

        oldest_payment_ids = Payment.objects.filter(
            loan_id__in=loans,
            payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
            account_payment_id__isnull=False
        ).exclude(is_restructured=True) \
            .order_by('loan', 'id').distinct('loan').values_list('id', flat=True)
        if oldest_payment_ids:
            redis_client.set_list(
                RedisKey.GRAB_OLDEST_PAYMENT_IDS, oldest_payment_ids, timedelta(hours=4))
            oldest_payment_ids = list(oldest_payment_ids)
    else:
        oldest_payment_ids = list(map(int, cached_oldest_payment_ids))
    return oldest_payment_ids


def get_total_batch_grab_data_for_koleko():
    total_payment_data = Payment.objects.not_paid_active().filter(
        id__in=get_oldest_grab_payment_ids()
    ).select_related('loan', 'loan__account').exclude(
        loan__loan_status=LoanStatusCodes.INACTIVE
    ).order_by('id').count()
    if not total_payment_data:
        return 0, 0

    return total_payment_data, int(math.ceil(total_payment_data / SPLIT_DATA_FOR_KOLEKO_PER))


def get_grab_data_for_koleko(last_payment_id=None):
    filter_data = dict(id__in=get_oldest_grab_payment_ids())
    if last_payment_id:
        filter_data.update(id__gt=last_payment_id)
    return Payment.objects.not_paid_active().select_related('loan', 'loan__account').exclude(
        loan__loan_status=LoanStatusCodes.INACTIVE
    ).filter(
        **filter_data
    ).order_by('id')[:SPLIT_DATA_FOR_KOLEKO_PER]


def construct_data_koleko_format(payments):
    """
        format grab data to koleko
    """
    list_cpcrd_new_data = []
    list_cpcrd_ext_data = []
    list_payment_data = []
    for payment in payments.iterator():
        loan = payment.loan
        account = loan.account
        if not account:
            continue
        application = account.last_application
        if not application:
            continue

        customer = application.customer
        last_payment_date, last_payment_amount = payment.get_last_payment_event_date_and_amount()
        admin_fee = 0
        cpcrd_new_data = dict(
            CM_TYPE='GRAB',
            CM_CARD_NMBR=loan.loan_xid,
            CM_CUSTOMER_NMBR=application.application_xid,
            CM_DOMICILE_BRANCH='',
            CM_STATUS='',
            CM_DTE_PYMT_DUE=str(payment.due_date),
            CM_CARD_EXPIR_DTE='',
            CM_DELQ_COUNTER1='',
            CM_DELQ_COUNTER2='',
            CM_DELQ_COUNTER3='',
            CM_DELQ_COUNTER4='',
            CM_DELQ_COUNTER5='',
            CM_DELQ_COUNTER6='',
            CM_DELQ_COUNTER7='',
            CM_DELQ_COUNTER8='',
            CM_DELQ_COUNTER9='',
            CM_CURR_DUE=payment.due_amount,
            CM_PAST_DUE='',
            CM_30DAYS_DELQ='',
            CM_60DAYS_DELQ='',
            CM_90DAYS_DELQ='',
            CM_120DAYS_DELQ='',
            CM_150DAYS_DELQ='',
            CM_180DAYS_DELQ='',
            CM_210DAYS_DELQ='',
            CM_AMOUNT_DUE='',
            CM_CRLIMIT=0,#grab have limit but its wrong
            CM_DTE_CHGOFF_STAT_CHANGE='',
            CM_CHGOFF_STATUS_FLAG='',
            CM_BLOCK_CODE=account.status.show_status,
            CM_DTE_BLOCK_CODE='',
            CR_EU_CUSTOMER_CLASS='individu',
            CR_NAME_1=application.fullname,
            CR_EU_SEX='M' if application.gender == 'Pria' else 'F',
            CM_DTE_LST_PYMT=str(last_payment_date),
            CM_CYCLE=account.cycle_day,#tell koleko not using this because grab use daily deduction
            CM_DTE_INTO_COLLECTION='',
            CM_DTE_OPENED=str(loan.fund_transfer_ts),
            CM_RTL_MISC_FEES='',
            CM_TOT_PRINCIPAL='',
            CM_INTR_PER_DIEM='',
            CM_AMNT_OUTST_INSTL='',
            ACCT_NBR='',
            DPD=payment.due_late_days,
            CR_ADDR_1='',
            CR_OFFICE_PHONE='',
            CR_CO_OFFICE_PHONE='',
            CR_CITY='',
            CR_DTE_BIRTH='',
            CR_EMPLOYER='',
            CR_ADDL_EMAIL=application.email,
            CR_PLACE_OF_BIRTH='',
            CR_ZIP_CODE='',
            CR_C_ADDR_L1='',
            CR_C_ZIP_CODE='',
            MOB='',
            CR_ID_NUMBER='',
            CR_ID_TYPE='',
            CR_HANDPHONE=format_mobile_phone(application.mobile_phone_1),
            CR_OCCUPATION='',
            CR_GUARANTOR='',
            CR_GUARANTOR_PHONE='',
            CR_PROVINCE='',
            CM_TENOR=loan.loan_duration,
            CM_INSTALLMENT_AMOUNT=loan.installment_amount,
            CM_PK_NO='',
            CM_DTE_LIQUIDATE=str(loan.fund_transfer_ts),
            CM_OS_PRINCIPLE=loan.get_outstanding_principal(),
            CM_OS_INTEREST=loan.get_outstanding_interest(),
            CM_TOTAL_OS_AR=loan.get_total_outstanding_amount(),
            CM_COLLECTIBILITY='',
            CM_ACCT_BALANCE='',
            CM_PAID_PRICIPAL='',
            CM_PAID_INTEREST='',
            CM_PAID_CHARGE='',
            CM_HOLD_AMOUNT='',
            CM_AO_CODE='',
            CM_OFFICER_NAME='',
            CM_SECTOR_CODE='',
            CM_SECTOR_DESC='',
            CM_RESTRUCTURE_FLAG='',
            CM_DTE_RESTRUCTURE='',
            CM_FPD='',
            CM_CREDIT_SEGMEN='',
            CM_CHGOFF_PRICIPLE='',
            CM_NEXT_INST_PRINCIPAL='',
            CM_TOT_INTEREST='',
            CM_OS_BALANCE=loan.get_total_outstanding_due_amount(),
            CM_DTE_PK='',
            CM_INSTALLMENT_NO='',
            CM_TOTAL_CHARGE_FEE='',
            CM_CREDIT_LINE='',
            CM_CURRENCY_CODE='',
            CM_DTE_MAINT='',
            CM_AMOUNT_DUE_SIGN='',
            CM_DTE_LST_STMT_DAY='',
            CM_BUCKET='',
            FDP='',
            CR_HOME_PHONE='',
        )
        if loan.product:
            admin_fee = loan.product.admin_fee

        primary_payment_method = PaymentMethod.objects.filter(
            customer=customer, is_primary=True).first()
        va_number = ''
        if primary_payment_method:
            va_number = primary_payment_method.virtual_account
        cr_net_income = 0
        if application.monthly_income and application.monthly_expenses:
            cr_net_income = application.monthly_income - application.monthly_expenses
        cpcrd_ext_data = dict(
            CM_CARD_NMBR=loan.loan_xid,
            CM_APP_ORG='',
            CM_APPLICATION_TYPE='',
            CM_TRANSACTION_TYPE='',
            CM_FLAG_CONFISCATED='',
            CM_CONFISCATED_DATE='',
            CM_MGR_SALES='',
            CM_MGR_NAME='',
            CM_SOL_CODE='',
            CM_SALES_OFFICER_LEAD='',
            CM_SO_CODE='',
            CM_SALES_OFFICER='',
            CM_LATEST_APPROVER='',
            CM_NEW_TO_M1FLAG='',
            CM_INSURED_FLAG='',
            CM_LIQUID_AMT=loan.loan_amount - admin_fee,
            CM_PAY_ACC=va_number,
            CM_SERVICE_FEE='',
            CR_MARITAL_STATUS=application.marital_status,
            CR_SALUTATION='',
            CR_NATIONALITY=customer.country,
            CR_MOTHER_NM=application.customer_mother_maiden_name,
            CR_HANDPHONE2=format_mobile_phone(application.mobile_phone_2),
            CR_COMPANY_SUB_DISTRICT='',
            CR_COMPANY_DISTRICT='',
            CM_COMPANY_CITY_CODE='',
            CR_COMPANY_CITY='',
            CR_ADDR_SUB_DISTRICT='',
            CR_ADDR_DISTRICT='',
            CM_COMPANY_PROVINCE_CODE='',
            CM_COMPANY_PROVINCE='',
            CM_OCCUPATION_CODE='',
            CR_P='',
            CR_EMPLOYMENT_P_CODE='',
            CR_EMPLOYMENT_P_DESCRIPTION='',
            CM_INDUSTRY_GROUP='',
            CM_INDUSTRY_TYPE='',
            CM_SPOUSE_NAME='',
            CM_SPOUSE_PHONE='',
            CM_SPOUSE_HOMENO='',
            CR_EC_NAME='',
            CR_EC_PHONE='',
            CR_EC_RELATION='',
            CR_EC_LINE1='',
            CR_EC_LINE2='',
            CR_EC_LINE3='',
            CR_EC_SUB_DISTRICT='',
            CR_EC_DISTRICT='',
            CR_EC_CITY_CODE='',
            CR_EC_CITY='',
            CR_EC_PROVINCE_CODE='',
            CR_EC_PROVINCE='',
            CR_EC_ZIPCODE='',
            CR_GUARANTOR_LINE1='',
            CR_GUARANTOR_LINE2='',
            CR_GUARANTOR_LINE3='',
            CR_GUARANTOR_SUB_DISTRICT='',
            CR_GUARANTOR_DISTRICT='',
            CR_GUARANTOR_CITY_CODE='',
            CR_GUARANTOR_CITY='',
            CR_GUARANTOR_PROVINCECODE='',
            CR_GUARANTOR_PROVINCE='',
            CR_GUARANTOR_ZIPCODE='',
            CR_NET_INCOME=cr_net_income,
            CR_VIP_FLAG='',
            BRANCH_PROV_CODE='',
            BRANCH_CITY_CODE='',
            BRANCH_KEC_CODE='',
            BRANCH_KEL_CODE='',
            BROKEN_PROMISE='',
            REFRENCE_ID='',
            CR_VA_BCA='',
            CR_VA_PERMATA='',
            CR_VA_DANAMON='',
            CR_VA_MANDIRI='',
            CR_VA_MAYBANK='',
            CR_VA_BRI='',
        )
        installment_principal = payment.installment_principal
        installment_interest = payment.installment_interest
        installment_late_fee = payment.late_fee_amount
        installment_amount = installment_principal + installment_interest + installment_late_fee
        payment_data = dict(
            CM_CARD_NMBR=loan.loan_xid,
            POSTING_DATE=str(last_payment_date),
            EFFECTIVE_DATE=str(last_payment_date),
            DUE_DATE=str(payment.due_date),
            PAY_AMOUNT=last_payment_amount,
            ANGSURAN_POKOK=payment.paid_principal,
            ANGSURAN_DENDA=payment.paid_interest,
            DENDA=payment.paid_late_fee,
            ANGSURAN=installment_amount,
            PAYMENT_DESCRIPTION='',
            RESTRUCTURE_PAYMENT=0,
        )
        list_cpcrd_new_data.append(cpcrd_new_data)
        list_cpcrd_ext_data.append(cpcrd_ext_data)
        list_payment_data.append(payment_data)

    return list_cpcrd_new_data, list_cpcrd_ext_data, list_payment_data


def generate_csv_file_for_koleko(cpcrd_new_data, cpcrd_ext_data, cpcrd_payment_data):
    now_time = timezone.localtime(timezone.now())
    cpcrd_new_file_name = "cprd_new_{}.csv".format(now_time.strftime("%Y_%m_%d"))
    cpcrd_new_filepath = os.path.join(settings.MEDIA_ROOT, cpcrd_new_file_name)
    cpcrd_ext_file_name = "cprd_ext_{}.csv".format(now_time.strftime("%Y_%m_%d"))
    cpcrd_ext_filepath = os.path.join(settings.MEDIA_ROOT, cpcrd_ext_file_name)
    cpcrd_payment_file_name = "cprd_payment_{}.csv".format(now_time.strftime("%Y_%m_%d"))
    cpcrd_payment_filepath = os.path.join(settings.MEDIA_ROOT, cpcrd_payment_file_name)
    with open(cpcrd_new_filepath, 'w') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            ['PRODUCT CODE', 'NOMOR PINJAMAN', 'CIF NO.', 'KODE CABANG', 'STATUS REKENING',
             'DUE DATE', 'ORIGINAL MATURITY DT', 'CURRENT DUE COUNTER', 'PAST DUE COUNTER',
             '30DAYS DUE COUNTER', '60DAYS DUE COUNTER', '90DAYS DUE COUNTER',
             '120DAYS DUE COUNTER', '150DAYS DUE COUNTER', '180DAYS DUE COUNTER',
             '210DAYS DUE COUNTER', 'CURRENT DUE AMOUNT', 'PAST DUE AMOUNT', '30DAYS DUE AMOUNT',
             '60DAYS DUE AMOUNT', '90DAYS DUE AMOUNT', '120DAYS DUE AMOUNT', '150DAYS DUE AMOUNT',
             '180DAYS DUE AMOUNT', '210DAYS DUE AMOUNT', 'MINIMUM PAYMENT', 'LIMIT',
             'CHARGE OFF DATE', 'CHARGE OFF STATUS', 'BLOCK CODE', 'TANGGAL BLOCK CODE',
             'Customer Type', 'Customer Name', 'Gender', 'LAST PAYMENT DATE', 'CYCLE',
             'TANGGAL BERUBAH JADI NPL', 'OPEN DATE', 'LATE CHARGE', 'TUNGGAKAN POKOK',
             'INTEREST RATE', 'OUTSTANDING INSTALLMENT', 'NO. REK YANG AKAN DIDEBIT', 'DPD (HARI)',
             'Customer Address ', 'Office Phone 1', 'Office Phone 2', 'Customer City', 'Birth Date',
             'Company Name', 'Email Address', 'Place of Birth', 'Customer ZIPCode',
             'Company Address', 'Company ZIP Code', 'MOB', 'ID No.', 'ID Type', 'Phone 1',
             'Occupation', 'Guarantor Name', 'Guarantor Phone Number', 'Customer Province',
             'TENOR (BULAN)', 'INSTALLMENT AMOUNT', 'NO. PK', 'TANGGAL PENCAIRAN',
             'OUTSTANDING PRINCIPLE', 'OUTSTANDING INTEREST', 'TOTAL OUTSTANDING AR',
             'COLLECTABILITY', 'SALDO REK YANG AKAN DIDEBIT', 'POKOK YANG SUDAH DIBAYAR',
             'BUNGA YANG SUDAH DIBAYAR', 'DENDA YANG SUDAH DIBAYAR', 'HOLD AMOUNT', 'KODE A/O',
             'NAMA ACCOUNT OFFICER', 'KODE SEKTOR', 'SEKTOR DESCRIPTION', 'FLAG RESTRUCTURE',
             'RESTRUCTURE DATE', 'FIRST PAYMENT DEFAULT FLAG', 'SEGMENT KREDIT',
             'PRINCIPLE CHARGE-OFF', 'NEXT INSTALMENT PRINCIPLE', 'TUNGGAKAN BUNGA',
             'OUTSTANDING BALANCE', 'TANGGAL PK', 'INSTALLMENT NO.', 'SALDO DENDA',
             'CREDIT LINE NUMBER', 'SANDI VALUTA', 'TANGGAL UPDATE DATA',
             'TOTAL KEWAJIBAN', 'TANGGAL CETAK TAGIHAN', 'BUCKET', 'JUMLAH BAYAR AWAL',
             'customer home phone'
             ]
        )
        dict_writer = csv.DictWriter(csv_file, fieldnames=cpcrd_new_data[0].keys())
        dict_writer.writeheader()
        dict_writer.writerows(cpcrd_new_data)
    with open(cpcrd_ext_filepath, 'w') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            ['NOMOR PINJAMAN', 'ASAL APLIKASI', 'TIPE APLIKASI', 'TIPE TRANSAKSI', 'FLAG SITAAN',
             'TANGGAL SITAAN', 'KODE SALES MANAGER', 'NAMA SALES MANAGER', 'KODE SOL',
             'NAMA SALES OFFICER LEADER', 'KODE S/O', 'NAMA SALES OFFICER',
             'PENYETUJU KREDIT TERAKHIR', 'NEW TO M1 FLAG', 'INSURED FLAG', 'DISBURSEMENT AMOUNT',
             'PAYMENT ACCOUNT - VA NO.', 'SERVICE FEE', 'Marital Status', 'Salutation',
             'Nationality', 'Mother Name', 'Phone 2', 'Company Sub District', 'Company District',
             'Company City Code', 'Company City', 'Customer Sub District', 'Customer District',
             'Company Province Code', 'Company Province', 'Occupation Code', 'Position',
             'Employment Position Code', 'Employment Position Description', 'Industry Group',
             'Industry Type', 'Spouse Name', 'Spouse Phone Number', 'Spouse Home Number',
             'Emergency Contact Name', 'Emergency Contact Phone Number',
             'Emergency Contact Relationship', 'Emergency Address Line 1',
             'Emergency Address Line 2', 'Emergency Address Line 3', 'Emergency Sub District',
             'Emergency District', 'Emergency City Code', 'Emergency City',
             'Emergency Province Code', 'Emergency Province', 'Emergency ZIPCODE',
             'Guarantor Address Line 1', 'Guarantor Address Line 2', 'Guarantor Address Line 3',
             'Guarantor Sub District', 'Guarantor District', 'Guarantor City Code',
             'Guarantor City', 'Guarantor ProvinceCode', 'Guarantor Province',
             'Guarantor ZIPCODE', 'Net Income', 'VIP Flag', 'Branch province code',
             'Branch city code', 'Branch Kode Kecamatan', 'Branch Kode Kelurahan',
             'Flag Status PTP', 'refrence_id', 'VA BCA', 'VA PERMATA', 'VA DANAMON', 'VA MANDIRI ',
             'VA MAYBANK ', 'VA BRI'
             ]
        )
        dict_writer = csv.DictWriter(csv_file, fieldnames=cpcrd_ext_data[0].keys())
        dict_writer.writeheader()
        dict_writer.writerows(cpcrd_ext_data)
    with open(cpcrd_payment_filepath, 'w') as csv_file:
        dict_writer = csv.DictWriter(csv_file, fieldnames=cpcrd_payment_data[0].keys())
        dict_writer.writeheader()
        dict_writer.writerows(cpcrd_payment_data)
    # set file path for process next batch and deleted after uploaded
    redis_client = get_redis_client()
    redis_client.set(RedisKey.KOLEKO_CPCRD_NEW_FILE_PATH, cpcrd_new_filepath)
    redis_client.set(RedisKey.KOLEKO_CPCRD_EXT_FILE_PATH, cpcrd_ext_filepath)
    redis_client.set(RedisKey.KOLEKO_CPCRD_PAYMENT_FILE_PATH, cpcrd_payment_filepath)


def process_next_batch_koleko_data_to_csv_file(cpcrd_new_data, cpcrd_ext_data, cpcrd_payment_data):
    redis_client = get_redis_client()
    cpcrd_new_filepath = redis_client.get(RedisKey.KOLEKO_CPCRD_NEW_FILE_PATH)
    cpcrd_ext_filepath = redis_client.get(RedisKey.KOLEKO_CPCRD_EXT_FILE_PATH)
    cpcrd_payment_filepath = redis_client.get(RedisKey.KOLEKO_CPCRD_PAYMENT_FILE_PATH)
    if None in (cpcrd_new_filepath, cpcrd_ext_filepath, cpcrd_payment_filepath):
        return

    with open(cpcrd_new_filepath, 'a') as csv_file:
        dict_writer = csv.DictWriter(csv_file, fieldnames=cpcrd_new_data[0].keys())
        dict_writer.writerows(cpcrd_new_data)
    with open(cpcrd_ext_filepath, 'a') as csv_file:
        dict_writer = csv.DictWriter(csv_file, fieldnames=cpcrd_ext_data[0].keys())
        dict_writer.writerows(cpcrd_ext_data)
    with open(cpcrd_payment_filepath, 'a') as csv_file:
        dict_writer = csv.DictWriter(csv_file, fieldnames=cpcrd_payment_data[0].keys())
        dict_writer.writerows(cpcrd_payment_data)
