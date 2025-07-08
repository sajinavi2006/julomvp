from juloserver.channeling_loan.services.channeling_services import GeneralChannelingData as Mapping


class BNIDisbursementConst:
    FOLDER_NAME = "REIMBURSEMENT/REQUEST"
    FILENAME_FORMAT = "Reimbursement_{}_Julo{}.xlsx"  # first is datetime, second is counter
    FILENAME_DATETIME_FORMAT = "%d_%m_%Y_%H_%M_%S"
    FILENAME_RECAP_DATETIME_FORMAT = "%d_%m_%Y"
    SHEET_NAME = "BNI"

    HEADER_NO = "NO"
    HEADER_ALAMAT_KANTOR_4 = "ALAMAT KANTOR 4"  # there are 3 duplicated columns after this column
    HEADER_KOTA = "KOTA"
    HEADER_KOTA_POS = "KODE POS"
    HEADER_KOTA_AREA = "KODE AREA"

    DISBURSEMENT_DATA_MAPPING = {
        HEADER_NO: Mapping(value=1, is_hardcode=True),
        "ORG": Mapping(value="", is_hardcode=True),
        "LOGO": Mapping(value="", is_hardcode=True),
        "SUB TYPE": Mapping(value="", is_hardcode=True),
        "APP ID": Mapping(value="loan.loan_xid"),
        "CUST NUM": Mapping(value="", is_hardcode=True),
        "CUST NUM CORPORATE": Mapping(value="", is_hardcode=True),
        "EMPLOYEE REF CODE": Mapping(value="", is_hardcode=True),
        "SOURCE CODE": Mapping(value="", is_hardcode=True),
        "NAMA KTP": Mapping(value="detokenize_customer.fullname", length=30),
        "NAMA PADA KARTU": Mapping(value="detokenize_customer.fullname", length=20),
        "DOB": Mapping(value="customer.dob", output_format="%d-%m-%Y"),
        "JENIS KELAMIN": Mapping(value="customer.gender", length=1),
        "NO KTP": Mapping(value="detokenize_customer.nik", length=16),
        "NAMA IBU KANDUNG": Mapping(value="customer.mother_maiden_name", length=20),
        "JABATAN": Mapping(value="customer.job_type"),
        "PENGHASILAN GAJI": Mapping(value="customer.monthly_income"),
        "NO REKENING": Mapping(value="loan.bank_account_destination.account_number"),
        "CREDIT LIMIT": Mapping(value="loan.loan_amount"),
        "TANGGAL TAGIHAN": Mapping(
            value="first_payment.due_date.day", function_post_mapping="format_tanggal_tagihan"
        ),
        "ALAMAT RUMAH 1": Mapping(value="customer.address_street_num", length=30),
        "ALAMAT RUMAH 2": Mapping(value="customer.address_street_num", length=30),
        "ALAMAT RUMAH 3": Mapping(value="customer.address_street_num", length=30),
        "ALAMAT RUMAH 4": Mapping(value="customer.address_street_num", length=30),
        HEADER_KOTA: Mapping(value="customer.address_kabupaten"),
        HEADER_KOTA_POS: Mapping(value="customer.address_kodepos"),
        HEADER_KOTA_AREA: Mapping(value="", is_hardcode=True),
        "TELP RUMAH": Mapping(value="detokenize_customer.phone"),
        "ALAMAT KANTOR 1": Mapping(value="customer.address_street_num", length=30),
        "ALAMAT KANTOR 2": Mapping(value="customer.address_street_num", length=30),
        "ALAMAT KANTOR 3": Mapping(value="customer.address_street_num", length=30),
        HEADER_ALAMAT_KANTOR_4: Mapping(value="customer.address_street_num", length=30),
        # The fields below are duplicated with the above fields but exist in the Excel template.
        # => Will handle it in services
        # HEADER_KOTA: Mapping(value="customer.address_kabupaten"),
        # HEADER_KOTA_POS: Mapping(value="customer.address_kodepos"),
        # HEADER_KOTA_AREA: Mapping(value="", is_hardcode=True),
        "TELP KANTOR": Mapping(value="detokenize_customer.phone"),
        "HANDPHONE": Mapping(value="detokenize_customer.phone"),
        "EMERGENCY CONTACT": Mapping(
            value="customer", function_post_mapping="get_emergency_contact"
        ),
        "HUBUNGAN": Mapping(value="customer", function_post_mapping="get_hubungan"),
        "KODE TELP EC": Mapping(value="", is_hardcode=True),
        "TELP EC": Mapping(value="customer", function_post_mapping="get_telp_ec"),
        "PENGIRIMAN BILLING": Mapping(value="", is_hardcode=True),
        "PENGIRIMAN KARTU": Mapping(value="", is_hardcode=True),
        "NO KK BANK LAIN": Mapping(value="", is_hardcode=True),
        "IDENTITAS PADA KARTU": Mapping(value="", is_hardcode=True),
        "CASH LIMIT": Mapping(value="loan.loan_amount"),
        "NPWP": Mapping(value="detokenize_customer.nik"),
        "TENOR CICILAN": Mapping(value="loan.loan_duration"),
        "POB": Mapping(value="customer.birth_place"),
    }


class BNIRepaymentConst:
    FOLDER_NAME = "REPAYMENT/REQUEST"
    FILENAME_FORMAT = "Repayment_{}_Julo{}.xlsx"  # first is dd_mm_yyyy, second is counter
    FILENAME_DATETIME_FORMAT = "%d_%m_%Y_%H_%M_%S"
    SHEET_NAME = "BNI"
    HEADER_NO = "Nomor"

    # there no type for this map, only map with uploaded excel data
    REPAYMENT_HEADER_DATA_MAPPING = {
        "loan_xid": "Loan ID",
        "fullname": "Nama",
        "mobile_phone_1": "No HP",
        "dob": "DOB",
        "ktp": "KTP Number",
        "address_street_num": "Alamat",
        "loan_amount": "Credit Limit",
        "loan_duration": "Tenor",
        "payment_number": "Sequence",
        "due_date": "Cycle",
        "principal_amount": "Pokok",
        "interest_amount": "Bunga",
        "latefee_amount": "Late Fee",
        "due_amount": "Total Cicilan",
        "event_date": "Tanggal Payment Cust ke JULO",
        "posting_date": "Tanggal Payment JULO ke BNI",
        "event_payment": "Payment",
        "status_payment": "Status Payment",
    }

    REPAYMENT_EXTRA_HEADER = [
        HEADER_NO,
        "Cust Number",
        "Account Number",
    ]


class BNISupportingDisbursementDocumentConst:
    FOLDER_NAME = "SUPPORTINGDOC"
    FILENAME_FORMAT = "SupportingDoc_{}_Julo{}.zip"  # first is datetime, second is counter
    FILENAME_DATETIME_FORMAT = "%d_%m_%Y_%H_%M_%S"
    FILENAME_RECAP_DATETIME_FORMAT = "%d_%m_%Y"

    SKRTP = "skrtp"
    KTP = "ktp"
    SELFIE = "selfie"

    LIST_SKRTP_DOCUMENT_TYPE = ['sphp_julo', 'skrtp_julo']

    MAPPING_FILENAME_FORMAT = {  # first is the numerical order
        SKRTP: "{}_skrtp.pdf",
        KTP: "{}_ktp.jpg",
        SELFIE: "{}_selfie.jpg",
    }


# default BNI interest based on tenor
BNI_DEFAULT_INTEREST = {
    '1': 10.75,
    '2': 8.06,
    '3': 7.17,
    '4': 6.72,
    '5': 6.45,
    '6': 6.27,
    '7': 6.14,
    '8': 6.05,
    '9': 5.97,
    '10': 5.91,
    '11': 5.86,
    '12': 5.82,
}
