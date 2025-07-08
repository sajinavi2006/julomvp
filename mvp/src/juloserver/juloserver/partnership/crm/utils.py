PRODUCT_FINANCING_LOAN_CREATION_UPLOAD_MAPPING_FIELDS = [
    ("Application XID", "application_xid"),
    ("Name", "fullname"),
    ("Product ID", "product_id"),
    ("Amount Requested (Rp)", "loan_amount_request"),
    ("Tenor", "loan_duration"),
    ("Tenor type", "loan_duration_type"),
    ("Interest Rate", "interest_rate"),
    ("Provision Rate", "origination_fee_pct"),
    ("Loan Start Date", "loan_start_date"),
]


def format_product_financing_loan_creation_csv_upload(raw_data: dict) -> dict:
    formated_data = {}
    for raw_field, formated_field in PRODUCT_FINANCING_LOAN_CREATION_UPLOAD_MAPPING_FIELDS:
        formated_data[formated_field] = raw_data[raw_field]
    return formated_data
