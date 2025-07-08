from juloserver.channeling_loan.constants.constants import ChannelingActionTypeConst
from juloserver.channeling_loan.services.channeling_services import GeneralChannelingData as Mapping

JULO_ORG_ID_GIVEN_BY_DBS = "IDJULO01"
DBS_API_CONTENT_TYPE = "text/plain"


class DBSDisbursementConst:
    GPG_ENCRYPT_COMPRESS_ALGORITHM = "zip"

    PREFIX_CONTRACT_CODE = "JUL"
    PARTY_DOC_TYPE_E_KTP = "E-KTP"
    PHONE_TYPE_HOME = "HOME"
    PHONE_TYPE_MOBILE = "MOBILE"
    EMAIL_TYPE_PERSONAL = "PERSONAL"
    ADDRESS_TYPE_PERMANENT_RESIDENTIAL = "PERMANENTRESIDENTIAL"
    ADDRESS_TYPE_PERMANENT_RESIDENTIAL_IDENTIFICATION = "OTHERS"
    ADDRESS_TYPE_GOVERNMENT_ID = "GOVERNMENTID"
    ADDRESS_TYPE_GOVERNMENT_ID_IDENTIFICATION = "E-KTP"
    CURRENCY = "IDR"
    TAX_PAYER_TYPE_NO = "N"
    LOAN_CODE = "IDREGJFSQ11"
    LOAN_ACCOUNT_NUMBER = "04603073320141246"
    BENEFICIARY_NAME = "PT JULO TEKNOLOGI FINANSIAL"
    PROGRAM = "JUL"
    TYPE = "581"
    DOWN_PAYMENT = "0"
    COMMODITY_CATEGORY_CODE = "Cashloan"
    TYPE_PF_GOODS = "JULO"
    TYPE_OF_GOODS = "JUL Cash Loan"
    RECORD_INDICATOR = "D"

    REQUEST_TYPE_API_IN_LOG = '[POST] send_loan'
    REQUEST_TYPE_CALLBACK_IN_LOG = '[POST] callback'

    REQUEST_BODY_DATA_MAPPING = {
        "header": {
            "msgId": Mapping(
                value="", allow_null=False, is_hardcode=True
            ),  # update in service for each request
            "orgId": Mapping(value=JULO_ORG_ID_GIVEN_BY_DBS, allow_null=False, is_hardcode=True),
            "timeStamp": Mapping(
                value="current_ts", function_post_mapping="get_time_stamp", allow_null=False
            ),
        },
        "data": {
            "loanApplicationRequest": {
                "applicationType": Mapping(
                    value="loan", length=20, function_post_mapping="get_application_type"
                ),
                "applicationId": Mapping(
                    value="loan.loan_xid",
                    length=15,
                    function_post_mapping="get_contract_code",
                    allow_null=False,
                ),
                "partnerPartyId": None,
                "batchId": None,
                "retailDemographic": {
                    "partyDoc": [
                        {
                            "docType": Mapping(
                                value=PARTY_DOC_TYPE_E_KTP, allow_null=False, is_hardcode=True
                            ),
                            "docNumber": Mapping(value="detokenize_customer.nik", allow_null=False),
                            "nameOnDoc": Mapping(
                                value="detokenize_customer.fullname", length=40, allow_null=False
                            ),
                            "docIssueDate": None,
                            "docIssueCtry": None,
                        }
                    ],
                    "partyName": {
                        "fullName": Mapping(
                            value="detokenize_customer.fullname", length=40, allow_null=False
                        ),
                        "name": {"firstName": None, "middleName": None, "lastName": None},
                        "nameSuffix": None,
                        "salutation": None,
                        "alias": None,
                    },
                    "dateOfBirth": Mapping(
                        value="customer.dob", output_format="%Y-%m-%d", allow_null=False
                    ),
                    "placeOfBirth": Mapping(
                        value="customer.birth_place", length=17, allow_null=False
                    ),
                    "gender": Mapping(
                        value="customer.gender",
                        length=1,
                        function_post_mapping="get_gender",
                        allow_null=False,
                    ),
                    "maritalStatus": Mapping(
                        value="customer.marital_status",
                        length=1,
                        function_post_mapping="get_marital_status",
                        allow_null=False,
                    ),
                    "fatherName": None,
                    "motherName": Mapping(
                        value="customer.mother_maiden_name", length=40, allow_null=False
                    ),
                    "spouseName": None,
                    "numberOfDependents": Mapping(
                        value="application.dependent or 0", data_type=int, allow_null=False
                    ),
                    "educationLevel": Mapping(
                        value="customer.last_education",
                        length=1,
                        function_post_mapping="get_education_level",
                        allow_null=False,
                    ),
                    "nationality": None,
                    "residenceCtry": None,
                    "residenceStatus": None,
                    "isResident": Mapping(value=True, data_type=bool, is_hardcode=True),
                    "isStaff": Mapping(value=True, data_type=bool, is_hardcode=True),
                    "estimatedNetWorth": None,
                    "currentResidencePeriod": {"numberOfYears": None, "numberOfMonths": None},
                    "creditSegment": None,
                    "incomeSegment": None,
                    "propensitySegment": None,
                    "score": None,
                    "scoreDate": None,
                    "amlRiskRating": Mapping(
                        value="customer",
                        allow_null=False,
                        length=1,
                        function_post_mapping="get_aml_risk_rating",
                    ),
                },
                "contactDetl": {
                    "phoneDetl": [
                        {
                            "phone": {
                                "phoneType": Mapping(
                                    value=PHONE_TYPE_HOME, allow_null=False, is_hardcode=True
                                ),
                                "phoneCtryCode": None,
                                "phoneAreaCode": None,
                                "phoneNumber": Mapping(
                                    value="detokenize_customer.phone", length=15, allow_null=False
                                ),
                                "phoneExtension": None,
                            },
                            "isPrefPhone": Mapping(
                                value=True, data_type=bool, allow_null=False, is_hardcode=True
                            ),
                        },
                        {
                            "phone": {
                                "phoneType": Mapping(
                                    value=PHONE_TYPE_MOBILE, allow_null=False, is_hardcode=True
                                ),
                                "phoneCtryCode": None,
                                "phoneAreaCode": None,
                                "phoneNumber": Mapping(
                                    value="detokenize_customer.phone", length=15, allow_null=False
                                ),
                                "phoneExtension": None,
                            },
                            "isPrefPhone": Mapping(
                                value=False, data_type=bool, allow_null=False, is_hardcode=True
                            ),
                        },
                    ],
                    "emailDetl": [
                        {
                            "emailAddressDetl": {
                                "emailAddressType": Mapping(
                                    value=EMAIL_TYPE_PERSONAL,
                                    allow_null=False,
                                    is_hardcode=True,
                                ),
                                "emailAddress": Mapping(
                                    value="detokenize_customer.email", length=320, allow_null=False
                                ),
                            },
                            "isPrefEmail": Mapping(
                                value=True, data_type=bool, allow_null=False, is_hardcode=True
                            ),
                        }
                    ],
                    "addressDetl": [
                        {
                            "addressId": None,
                            "addressType": Mapping(
                                value=ADDRESS_TYPE_PERMANENT_RESIDENTIAL,
                                allow_null=False,
                                is_hardcode=True,
                            ),
                            "addressIdentification": Mapping(
                                value=ADDRESS_TYPE_PERMANENT_RESIDENTIAL_IDENTIFICATION,
                                allow_null=False,
                                is_hardcode=True,
                            ),
                            "address": {
                                "addressLine1": Mapping(
                                    value="customer.address_street_num", length=40, allow_null=False
                                ),
                                "addressLine2": None,
                                "addressLine3": None,
                                "addressLine4": None,
                                "postalCode": Mapping(
                                    value="customer.address_kodepos",
                                    length=5,
                                    allow_null=False,
                                ),
                                "city": Mapping(
                                    value="customer.address_kabupaten", length=17, allow_null=False
                                ),
                                "districtCode": Mapping(
                                    value="rt_rw",
                                    length=2,
                                    function_post_mapping="get_district_code",
                                    allow_null=False,
                                ),
                                "districtName": Mapping(
                                    value="customer.address_kecamatan", length=20, allow_null=False
                                ),
                                "subDistrictCode": Mapping(
                                    value="rt_rw",
                                    length=3,
                                    function_post_mapping="get_sub_district_code",
                                    allow_null=False,
                                ),
                                "subDistrictName": Mapping(
                                    value="customer.address_kelurahan", length=20, allow_null=False
                                ),
                                "stateProvince": None,
                                "country": None,
                            },
                            "isCurrentAddress": Mapping(
                                value=True, data_type=bool, is_hardcode=True
                            ),
                            "isAadhaarAddress": Mapping(
                                value=False, data_type=bool, is_hardcode=True
                            ),
                            "isPreferredAddress": Mapping(
                                value=True, data_type=bool, allow_null=False, is_hardcode=True
                            ),
                        },
                        {
                            "addressId": None,
                            "addressType": Mapping(
                                value=ADDRESS_TYPE_GOVERNMENT_ID, allow_null=False, is_hardcode=True
                            ),
                            "addressIdentification": Mapping(
                                value=ADDRESS_TYPE_GOVERNMENT_ID_IDENTIFICATION,
                                allow_null=False,
                                is_hardcode=True,
                            ),
                            "address": {
                                "addressLine1": Mapping(
                                    value="customer.address_street_num", length=40, allow_null=False
                                ),
                                "addressLine2": None,
                                "addressLine3": None,
                                "addressLine4": None,
                                "postalCode": Mapping(
                                    value="customer.address_kodepos",
                                    length=5,
                                    allow_null=False,
                                ),
                                "city": Mapping(
                                    value="customer.address_kabupaten", length=17, allow_null=False
                                ),
                                "districtCode": Mapping(
                                    value="rt_rw",
                                    length=2,
                                    function_post_mapping="get_district_code",
                                    allow_null=False,
                                ),
                                "districtName": Mapping(
                                    value="customer.address_kecamatan", length=20, allow_null=False
                                ),
                                "subDistrictCode": Mapping(
                                    value="rt_rw",
                                    length=3,
                                    function_post_mapping="get_sub_district_code",
                                    allow_null=False,
                                ),
                                "subDistrictName": Mapping(
                                    value="customer.address_kelurahan", length=20, allow_null=False
                                ),
                                "stateProvince": None,
                                "country": None,
                            },
                            "isCurrentAddress": Mapping(
                                value=False, data_type=bool, is_hardcode=True
                            ),
                            "isAadhaarAddress": Mapping(
                                value=False, data_type=bool, is_hardcode=True
                            ),
                            "isPreferredAddress": Mapping(
                                value=False, data_type=bool, allow_null=False, is_hardcode=True
                            ),
                        },
                    ],
                },
                "employmentDetl": {
                    "employerName": Mapping(
                        value="customer.company_name", length=40, allow_null=False
                    ),
                    "employerPhone": Mapping(
                        value="customer",
                        length=40,
                        function_post_mapping="get_employer_phone",
                        allow_null=False
                    ),
                    "employerAddress": {
                        "addressLine1": Mapping(
                            value="customer",
                            length=40,
                            function_post_mapping="get_employer_address_street_num",
                            allow_null=False
                        ),
                        "postalCode": None,
                        "city": None,
                    },
                    "jobCode": Mapping(
                        value="customer",
                        length=2,
                        function_post_mapping="get_job_code",
                        allow_null=False,
                    ),
                    "jobTitle": Mapping(
                        value="customer.job_description", length=32, allow_null=False
                    ),
                    "industry": Mapping(
                        value="customer",
                        length=2,
                        function_post_mapping="get_job_industry",
                        allow_null=False,
                    ),
                    "occupation": None,
                    "isCurrentEmployment": Mapping(value=True, data_type=bool, is_hardcode=True),
                    "employmentStatus": Mapping(
                        value="application.employment_status",
                        length=1,
                        function_post_mapping="get_employment_status",
                        allow_null=False,
                    ),
                    "monthlyIncome": {
                        "amount": Mapping(
                            value="customer.monthly_income", data_type=int, allow_null=False
                        ),
                        "currency": Mapping(value=CURRENCY, allow_null=False, is_hardcode=True),
                    },
                    "annualIncome": {
                        "amount": Mapping(
                            value="customer.monthly_income*12", data_type=int, allow_null=False
                        ),
                        "currency": Mapping(value=CURRENCY, allow_null=False, is_hardcode=True),
                    },
                    "employmentPeriod": {
                        "numberOfYears": Mapping(
                            value="job_start",
                            length=2,
                            function_post_mapping="get_employment_period_in_years",
                            allow_null=False,
                        ),
                        "numberOfMonths": Mapping(
                            value="job_start",
                            length=2,
                            function_post_mapping="get_employment_period_in_months",
                            allow_null=False,
                        ),
                    },
                },
                "incomeTaxDetl": {
                    "isTaxpayer": Mapping(
                        value=TAX_PAYER_TYPE_NO, allow_null=False, is_hardcode=True
                    ),
                    "taxpayerIdentificationNumber": None,
                    "monthlyIncomeBasedOnDoc": {
                        "amount": Mapping(
                            value="customer.monthly_income", data_type=int, allow_null=False
                        ),
                        "currency": Mapping(value=CURRENCY, allow_null=False, is_hardcode=True),
                    },
                    "annualIncomeBasedOnDoc": {
                        "amount": Mapping(
                            value="customer.monthly_income*12", data_type=int, allow_null=False
                        ),
                        "currency": Mapping(value=CURRENCY, allow_null=False, is_hardcode=True),
                    },
                },
                "loanOfferDetl": [
                    {
                        "loanAmount": {
                            "amount": Mapping(
                                value="loan.loan_amount", data_type=int, allow_null=False
                            ),
                            "currency": Mapping(value=CURRENCY, allow_null=False, is_hardcode=True),
                        },
                        "loanCode": Mapping(value=LOAN_CODE, allow_null=False, is_hardcode=True),
                        "loanTenure": Mapping(
                            value="loan.loan_duration", length=2, data_type=int, allow_null=False
                        ),
                        "interestRate": Mapping(
                            value="channeling_loan_config",
                            data_type=int,
                            function_post_mapping="get_bank_yearly_interest_rate",
                            allow_null=False,
                        ),
                        "interestAmount": {
                            "amount": Mapping(
                                value="payments",
                                data_type=int,
                                function_post_mapping="get_total_bank_interest_amount",
                                allow_null=False,
                            ),
                            "currency": Mapping(value=CURRENCY, allow_null=False, is_hardcode=True),
                        },
                        "offerExpiryDate": None,
                        "instalmentAmount": {
                            "amount": Mapping(
                                value="payments",
                                data_type=int,
                                function_post_mapping="get_bank_installment_amount",
                                allow_null=False,
                            ),
                            "currency": Mapping(value=CURRENCY, allow_null=False, is_hardcode=True),
                        },
                        "disbursmentAmount": {
                            "amount": Mapping(
                                value="loan.loan_amount", data_type=int, allow_null=False
                            ),
                            "currency": Mapping(value=CURRENCY, allow_null=False, is_hardcode=True),
                        },
                        "dueDate": Mapping(
                            value="first_payment.due_date", output_format="%d", allow_null=False
                        ),
                        "receiptDate": Mapping(
                            value="current_ts", output_format="%Y-%m-%d", allow_null=False
                        ),
                        "signatureDate": Mapping(
                            value="loan.sphp_accepted_ts_or_cdate",
                            output_format="%Y-%m-%d",
                            allow_null=False,
                        ),
                    }
                ],
                "additionalDetl": {
                    "loanAccountNumber": Mapping(
                        value=LOAN_ACCOUNT_NUMBER, length=40, allow_null=False, is_hardcode=True
                    ),
                    "beneficiaryName": Mapping(
                        value=BENEFICIARY_NAME,
                        length=40,
                        allow_null=False,
                        is_hardcode=True,
                    ),
                    "totalLoanAmount": {
                        "amount": None,
                        "currency": Mapping(value=CURRENCY, is_hardcode=True),
                    },
                    "sanctionDate": None,
                    "sumOfObligation": {
                        "amount": None,
                        "currency": Mapping(value=CURRENCY, is_hardcode=True),
                    },
                    "applicationScoreBand": None,
                    "processingFee": {
                        "amount": None,
                        "currency": Mapping(value=CURRENCY, is_hardcode=True),
                    },
                    "annualInstalmentAmount": {
                        "amount": None,
                        "currency": Mapping(value=CURRENCY, is_hardcode=True),
                    },
                    "firstDrawdownDate": None,
                    "program": Mapping(
                        value=PROGRAM,
                        allow_null=False,
                        is_hardcode=True,
                    ),
                    "psCode": Mapping(
                        value=PROGRAM,
                        allow_null=False,
                        is_hardcode=True,
                    ),
                    "type": Mapping(
                        value=TYPE,
                        allow_null=False,
                        is_hardcode=True,
                    ),
                    "oth1": None,
                    "oth2": None,
                },
                "geoTaggingDetl": {"latitude": None, "longitude": None},
                "partnerLimitDetl": {
                    "totalApprovedLimit": {
                        "amount": Mapping(
                            value="loan.loan_amount", data_type=int, allow_null=False
                        ),
                        "currency": Mapping(value=CURRENCY, allow_null=False, is_hardcode=True),
                    },
                    "openingLimitBalance": {
                        "amount": None,
                        "currency": Mapping(value=CURRENCY, is_hardcode=True),
                    },
                    "closingLimitBalance": {
                        "amount": None,
                        "currency": Mapping(value=CURRENCY, is_hardcode=True),
                    },
                    "limitExpiryDate": None,
                    "revisedTotalApprovedLimit": {
                        "amount": None,
                        "currency": Mapping(value=CURRENCY, is_hardcode=True),
                    },
                    "revisedOpeningLimitBalance": {
                        "amount": None,
                        "currency": Mapping(value=CURRENCY, is_hardcode=True),
                    },
                    "revisedClosingLimitBalance": {
                        "amount": None,
                        "currency": Mapping(value=CURRENCY, is_hardcode=True),
                    },
                    "revisedLimitExpiryDate": None,
                },
                "contractInfo": {
                    "agreementDate": Mapping(
                        value="loan.sphp_accepted_ts_or_cdate",
                        output_format="%Y-%m-%d", allow_null=False
                    ),
                    "areaBusiness": None,
                    "assignPrincipal": Mapping(
                        value="loan.loan_amount", data_type=int, allow_null=False
                    ),
                    "bankInstallment": Mapping(
                        value="payments",
                        data_type=int,
                        function_post_mapping="get_bank_installment_amount",
                        allow_null=False,
                    ),
                    "bankInterest": Mapping(
                        value="payments",
                        data_type=int,
                        function_post_mapping="get_total_bank_interest_amount",
                        allow_null=False,
                    ),
                    "bankInterestRate": Mapping(
                        value="channeling_loan_config",
                        data_type=int,
                        function_post_mapping="get_bank_yearly_interest_rate",
                        allow_null=False,
                    ),
                    "bankPrincipal": Mapping(
                        value="loan.loan_amount", data_type=int, allow_null=False
                    ),
                    "bankTenor": Mapping(
                        value="loan.loan_duration", data_type=int, allow_null=False
                    ),
                    "codeInArear": None,
                    "contractCode": Mapping(
                        value="loan.loan_xid",
                        function_post_mapping="get_contract_code",
                        allow_null=False,
                    ),
                    "creditLimit": Mapping(value="account_limit.set_limit", allow_null=False),
                    "creditScoring": Mapping(
                        value="customer.id",
                        function_post_mapping="get_customer_credit_score",
                        allow_null=False
                    ),
                    "customerId": None,
                    "customerName": Mapping(value="detokenize_customer.fullname", allow_null=False),
                    "downPayment": Mapping(value=DOWN_PAYMENT, allow_null=False, is_hardcode=True),
                    "effectiveDate": Mapping(
                        value="loan.fund_transfer_ts_or_cdate",
                        output_format="%Y-%m-%d", allow_null=False
                    ),
                    "firstDueDate": Mapping(
                        value="first_payment.due_date", output_format="%Y-%m-%d", allow_null=False
                    ),
                    "fullContractNumber": None,
                    "goodsPriceInsurance": None,
                    "goodsValue": Mapping(
                        value="loan.loan_amount", data_type=int, allow_null=False
                    ),
                    "initialPrincipal": Mapping(
                        value="loan.loan_amount", data_type=int, allow_null=False
                    ),
                    "insuranceAmount": None,
                    "insuranceCompany": None,
                    "lastDueDate": Mapping(
                        value="last_payment.due_date", output_format="%Y-%m-%d", allow_null=False
                    ),
                    "mfBranchCode": None,
                    "mfBranchName": None,
                    "mfInitialTenor": None,
                    "mfInstallment": Mapping(
                        value="first_payment.due_amount", data_type=int, allow_null=False
                    ),
                    "mfInterestRate": Mapping(
                        value="loan.interest_rate_monthly",
                        data_type=int,
                        function_post_mapping="get_yearly_interest_rate",
                        allow_null=False,
                    ),
                    "premiumPayment": None,
                    "purposeUsage": None,
                    "remainingCreditLimit": None,
                    "sellerType": Mapping(
                        value="loan.loan_duration",
                        function_post_mapping="get_seller_type",
                        allow_null=False,
                    ),
                },
                "goodsInfo": {
                    "code": None,
                    "commodityCategoryCode": Mapping(
                        value=COMMODITY_CATEGORY_CODE,
                        allow_null=False,
                        is_hardcode=True,
                    ),
                    "contractCode": Mapping(
                        value="loan.loan_xid",
                        function_post_mapping="get_contract_code",
                        allow_null=False,
                    ),
                    "goodsPrice": Mapping(
                        value="loan.loan_disbursement_amount", data_type=int, allow_null=False
                    ),
                    "producer": None,
                    "typeOfGoods": Mapping(
                        value=TYPE_OF_GOODS,
                        allow_null=False,
                        is_hardcode=True,
                    ),
                    "typePfGoods": Mapping(
                        value=TYPE_PF_GOODS,
                        allow_null=False,
                        is_hardcode=True,
                    ),
                },
                "loanScheduleList": Mapping(value="", is_hardcode=True),  # construct later
                "campaignCode": Mapping(
                    value=PROGRAM,
                    allow_null=False,
                    is_hardcode=True,
                ),
                "isApplicationComplete": Mapping(
                    value=True, data_type=bool, allow_null=False, is_hardcode=True
                ),
                "consentFlag": Mapping(value=True, data_type=bool, is_hardcode=True),
                "channel": Mapping(
                    value=PROGRAM,
                    allow_null=False,
                    is_hardcode=True,
                ),
                "offerId": None,
            }
        },
    }

    LOAN_SCHEDULE_ELEMENT_MAPPING = {
        "dueDate": Mapping(value="payment.due_date", output_format="%Y-%m-%d", allow_null=False),
        "contractCode": Mapping(
            value="loan.loan_xid", function_post_mapping="get_contract_code", allow_null=False
        ),
        "installmentAmount": Mapping(
            value="channeling_loan_payment.due_amount", data_type=int, allow_null=False
        ),
        "installmentNumber": Mapping(value="payment.payment_number", allow_null=False),
        "interest": Mapping(
            value="channeling_loan_payment.interest_amount", data_type=int, allow_null=False
        ),
        "principal": Mapping(
            value="channeling_loan_payment.principal_amount", data_type=int, allow_null=False
        ),
        "recordIndicator": Mapping(value=RECORD_INDICATOR, allow_null=False, is_hardcode=True),
    }


class DBSApplicationTypeConst(object):
    NEW = "NEW"
    EXISTING = "EXISTING"


class DBSEducationConst(object):
    NOT_FOUND = 7
    LIST = {
        "TK": 7,
        "SD": 6,
        "SLTP": 5,
        "SLTA": 4,
        "DIPLOMA": 2,
        "S1": 1,
        "S2": 1,
        "S3": 1,
    }


class DBSChannelingUpdateLoanStatusConst(object):
    ERROR_CODE_VALIDATION_ERROR = "S801"
    ERROR_MESSAGE_VALIDATION_ERROR = (
        "Your request cannot be validated. Please rectify the input data"
    )
    ERROR_CODE_INVALID_INPUT_PARAM = "S997"
    ERROR_MESSAGE_INVALID_INPUT_PARAM = (
        "Your request cannot be validated. Please verify the input parameters"
    )

    HTTP_X_DBS_UUID = 'HTTP_X_DBS_UUID'
    HTTP_X_DBS_ORG_ID = 'HTTP_X_DBS_ORG_ID'
    HTTP_X_API_KEY = 'HTTP_X_API_KEY'

    HTTP_REQUIRED_HEADERS = [
        HTTP_X_DBS_UUID,
        HTTP_X_DBS_ORG_ID,
    ]

    HTTP_OPTIONAL_HEADERS = [
        HTTP_X_API_KEY,
        'HTTP_X_DBS_TIMESTAMP',
        'HTTP_X_DBS_CLIENTID',
        'HTTP_X_DBS_ACCESSTOKEN',
        'HTTP_X_DBS_ACCEPT_VERSION',
        'HTTP_X_DBS_SERVICINGCOUNTRY',
    ]


class DBSRepaymentConst:
    REQUEST_FOLDER_NAME = "repayment/request/"
    APPROVAL_FOLDER_NAME = "repayment/approval/"
    FILENAME_FORMAT = "JUL_PAYMENT_REGULAR_{}{}.xlsx"  # first is date, second is counter
    FILENAME_DATE_FORMAT = "%y%m%d"
    SHEET_NAME = "Sheet1"
    LOAN_ACC_NUMBER_PREFIX = "88"

    REPAYMENT_DATA_HEADER_DICTIONARY = {
        "loan_xid": "Loan Acc Number",
        "event_payment": "Amount",
        "event_date": "Trans_date",
        "sol_id": "SOL ID",
    }


class DBSReconciliationConst:
    REQUEST_FOLDER_NAME = "reconciliation/request/"
    APPROVAL_FOLDER_NAME = "reconciliation/approval/"
    FILENAME_FORMAT = "JUL_RECON_MONTHEND_{}{}.csv"  # first is date, second is counter
    FILENAME_DATE_FORMAT = "%y%m%d"

    RECONCILIATION_DATA_HEADER_LIST = [
        "partner_contract_number",
        "reconciliation_date",
        "outstanding",
        "dpd",
    ]


class DBSDisbursementDocumentMappingConst:
    DISBURSEMENT_TYPE = "581"
    COMPANY_ADDRESS = "ID"
    COMPANY_CITY = "ID"
    COMPANY_POSTAL_CODE = "12345"
    CO_TEL_NUMBER = "219999999"
    JOB_STATUS = "P"
    LOAN_CODE = "IDREGJFSQ11"
    BENEFICIARY_NAME = "PT JULO TEKNOLOGI FINANSIAL"
    LOAN_ACCOUNT_NUMBER = "460307123456789"
    PREFIX_CONTRACT_CODE = "JUL"
    PROGRAM = "JUL"
    SOURCE_CODE = "JUL"
    CAMPAIGN_CODE = "JUL"
    MF_BRANCH = "JUL"
    SELLER_TYPE = "JUL"
    NPWP_DOC_FLAG = "N"
    INSURANCE_AMOUNT = "0"
    PREMIUM_PAYMENT = "E"
    CREDIT_SCORING = "R1"
    DOWN_PAYMENT = "0"
    INSURANCE_COMPANY = ""
    AREA_BUSINESS = "4190"
    PURPOSE_USAGE = "K"
    CODE_IN_AREAR = "0"
    COMMODITY_CATEGORY_CODE = "Cashloan"
    PRODUCER = "Cashloan"
    TYPE_PF_GOODS = "JULO"
    TYPE_OF_GOODS = "JUL Cash Loan"
    RECORD_INDICATOR = "D"
    FILTER = ""

    APPLICATION_MAPPING = {
        "TYPE": Mapping(value=DISBURSEMENT_TYPE, is_hardcode=True, allow_null=False, length=3),
        "RECEIPT_DATE": Mapping(
            value="current_ts", allow_null=False, output_format="%d%m%Y", length=10
        ),
        "NAME": Mapping(value="detokenize_customer.fullname", allow_null=False, length=40),
        "NAME_BASED_ON_ID": Mapping(
            value="detokenize_customer.fullname", allow_null=False, length=40
        ),
        "NICK_NAME": Mapping(value="detokenize_customer.fullname", allow_null=False, length=20),
        "MOTHER_MAIDEN_NAME": Mapping(
            value="customer.mother_maiden_name", allow_null=False, length=40
        ),
        "GENDER": Mapping(
            value="customer.gender", function_post_mapping="get_gender", allow_null=False, length=1
        ),
        "PLACE_OF_BIRTH": Mapping(value="customer.birth_place", allow_null=False, length=17),
        "DATE_OF_BIRTH": Mapping(
            value="customer.dob", allow_null=False, output_format="%d%m%Y", length=8
        ),
        "KTP_NUMBER": Mapping(value="detokenize_customer.nik", allow_null=False, length=23),
        "EDUCATIONAL_LEVEL": Mapping(
            value="customer.last_education",
            allow_null=False,
            length=1,
            function_post_mapping="get_education_level",
        ),
        "MARITAL_STATUS": Mapping(
            value="customer.marital_status",
            allow_null=False,
            length=1,
            function_post_mapping="get_marital_status",
        ),
        "NUMBER_OF_DEPENDENTS": Mapping(
            value="application.dependent or 0",
            allow_null=False,
            length=2,
        ),
        "HOME_CURRENT_ADDRESS_1": Mapping(
            value="customer.address_street_num",
            allow_null=False,
            length=40,
        ),
        "HOME_CURRENT_ADDRESS_2": Mapping(value="", is_hardcode=True, length=40),
        "HOME_CURRENT_ADDRESS_3": Mapping(value="", is_hardcode=True, length=40),
        "HOME_DISTRICT_CODE": Mapping(
            value="ocr_ktp_result.rt_rw",
            allow_null=False,
            length=2,
            function_post_mapping="get_district_code",
        ),
        "HOME_SUB_DISTRICT_CODE": Mapping(
            value="ocr_ktp_result.rt_rw",
            allow_null=False,
            length=3,
            function_post_mapping="get_sub_district_code",
        ),
        "HOME_SUB_DISTRICT_NAME": Mapping(
            value="customer.address_kelurahan",
            allow_null=False,
            length=20,
        ),
        "HOME_DISTRICT_NAME": Mapping(
            value="customer.address_kecamatan",
            allow_null=False,
            length=20,
        ),
        "HOME_CITY": Mapping(
            value="customer.address_kabupaten",
            allow_null=False,
            length=17,
        ),
        "HOME_POSTAL_CODE": Mapping(
            value="customer.address_kodepos",
            allow_null=False,
            length=5,
        ),
        "ID_CARD_ADDRESS_1": Mapping(
            value="customer.address_street_num",
            allow_null=False,
            length=40,
        ),
        "ID_CARD_ADDRESS_2": Mapping(value="", is_hardcode=True, length=40),
        "ID_CARD_ADDRESS_3": Mapping(value="", is_hardcode=True, length=40),
        "ID_CARD_SUB_DISTRICT_CODE": Mapping(
            value="ocr_ktp_result.rt_rw",
            allow_null=False,
            length=3,
            function_post_mapping="get_sub_district_code",
        ),
        "ID_CARD_DISTRICT_CODE": Mapping(
            value="ocr_ktp_result.rt_rw",
            allow_null=False,
            length=2,
            function_post_mapping="get_district_code",
        ),
        "ID_CARD_SUB_DISTRICT_NAME": Mapping(
            value="customer.address_kelurahan",
            allow_null=False,
            length=20,
        ),
        "ID_CARD_DISTRICT_NAME": Mapping(
            value="customer.address_kecamatan",
            allow_null=False,
            length=20,
        ),
        "ID_CARD_CITY": Mapping(
            value="customer.address_kabupaten",
            allow_null=False,
            length=20,
        ),
        "HOME_TEL_NUMBER": Mapping(
            value="detokenize_customer.phone",
            allow_null=False,
            length=15,
        ),
        "MOBILE_TEL_NUMBER": Mapping(
            value="detokenize_customer.phone",
            allow_null=False,
            length=17,
        ),
        "MOBILE_TEL_NUMBER_2": Mapping(value="", is_hardcode=True, length=17),
        "COMPANY_NAME": Mapping(value="customer.company_name", allow_null=False, length=40),
        "COMPANY_ADDRESS_1": Mapping(
            value=COMPANY_ADDRESS, is_hardcode=True, allow_null=False, length=40
        ),
        "COMPANY_CITY": Mapping(value=COMPANY_CITY, is_hardcode=True, allow_null=False, length=20),
        "COMPANY_POSTAL_CODE": Mapping(
            value=COMPANY_POSTAL_CODE, is_hardcode=True, allow_null=False, length=5
        ),
        "CO_TEL_NUMBER": Mapping(
            value=CO_TEL_NUMBER, is_hardcode=True, allow_null=False, length=15
        ),
        "POSITION": Mapping(value="customer.job_description", allow_null=False, length=23),
        "POSITION_CODE": Mapping(
            value="customer",
            allow_null=False,
            length=2,
            function_post_mapping="get_job_code",
        ),
        "NATURE_OF_BUSINESS": Mapping(
            value="customer",
            allow_null=False,
            length=2,
            function_post_mapping="get_job_industry",
        ),
        "JOB_STATUS": Mapping(value=JOB_STATUS, is_hardcode=True, allow_null=False, length=1),
        "TOTAL_LENGTH_ON_JOB": Mapping(
            value="job_start",
            allow_null=False,
            length=4,
            function_post_mapping="get_employment_period",
        ),
        "DECLARED_INCOME_12_MONTHS": Mapping(
            value="customer.monthly_income*12",
            allow_null=False,
            length=17,
        ),
        "MONTHLY_INCOME_BASED_ON_DOC": Mapping(
            value="customer.monthly_income",
            allow_null=False,
            length=17,
        ),
        "ID_POSTAL_CODE": Mapping(
            value="customer.address_kodepos",
            allow_null=False,
            length=5,
        ),
        "EMERGENCY_CONT_NAME": Mapping(value="", is_hardcode=True, length=40),
        "EMERGENCY_RELATIONSHIP": Mapping(value="", is_hardcode=True, length=1),
        "EMERGENCY_MOBILE_TEL": Mapping(value="", is_hardcode=True, length=17),
        "TAX_NUMBER": Mapping(value="", is_hardcode=True, length=17),
        "LOAN_AMOUNT_REQUEST": Mapping(
            value="loan.loan_amount",
            allow_null=False,
            length=17,
        ),
        "LOAN_CODE": Mapping(value=LOAN_CODE, is_hardcode=True, allow_null=False, length=17),
        "LOAN_TENOR": Mapping(
            value="loan.loan_duration",
            allow_null=False,
            length=2,
        ),
        "BENEFICIARY_NAME": Mapping(
            value=BENEFICIARY_NAME,
            allow_null=False,
            length=40,
            is_hardcode=True,
        ),
        "ACC_NO": Mapping(
            value=LOAN_ACCOUNT_NUMBER,
            allow_null=False,
            length=40,
            is_hardcode=True,
        ),
        "APPLICATION_REFERENCE_NUMBER": Mapping(
            value="loan.loan_xid",
            allow_null=False,
            length=15,
            function_post_mapping="get_contract_code",
        ),
        "SOURCE_CODE": Mapping(
            value=SOURCE_CODE,
            allow_null=False,
            length=5,
            is_hardcode=True,
        ),
        "CAMPAIGN_CODE": Mapping(
            value=CAMPAIGN_CODE,
            allow_null=False,
            length=5,
            is_hardcode=True,
        ),
        "SIGNATURE_DATE": Mapping(
            value="loan.sphp_accepted_ts_or_cdate",
            allow_null=False,
            length=8,
            output_format="%d%m%Y",
        ),
        "EMAIL_ADDRESS": Mapping(
            value="detokenize_customer.email",
            allow_null=False,
            length=40,
        ),
        "PS_CODE": Mapping(
            value=PROGRAM,
            allow_null=False,
            length=5,
            is_hardcode=True,
        ),
        "PARTNER_INTEREST_RATE": Mapping(
            value="channeling_loan_config",
            allow_null=False,
            length=8,
            function_post_mapping="get_bank_yearly_interest_rate",
        ),
        "DISB_FIXED_AMT_3": Mapping(
            value="loan.loan_amount",
            allow_null=False,
            length=9,
        ),
        "NPWP_DOC_FLAG": Mapping(value=NPWP_DOC_FLAG, allow_null=False, length=1, is_hardcode=True),
        "AML_RISK_RATING": Mapping(
            value="customer",
            allow_null=False,
            length=1,
            function_post_mapping="get_aml_risk_rating",
        ),
        "CURRENT_COMPANY_ON_JOB_YY": Mapping(
            value="job_start",
            allow_null=False,
            length=2,
            function_post_mapping="get_current_company_on_job_in_years",
        ),
        "CURRENT_COMPANY_ON_JOB_MM": Mapping(
            value="job_start",
            allow_null=False,
            length=2,
            function_post_mapping="get_current_company_on_job_in_months",
        ),
        "PROGRAM": Mapping(
            value=PROGRAM,
            allow_null=False,
            length=40,
            is_hardcode=True,
        ),
        "PARTNER_INTEREST_AMOUNT": Mapping(
            value="payments",
            allow_null=False,
            length=17,
            function_post_mapping="get_total_bank_interest_amount",
        ),
        "RECOMMENDED_LIMIT": Mapping(
            value="loan.loan_amount",
            allow_null=False,
            length=17,
        ),
        "FINAL_INCOME": Mapping(
            value="customer.monthly_income",
            allow_null=False,
            length=17,
        ),
        "DUE_DATE": Mapping(
            value="first_payment.due_date", allow_null=False, length=2, output_format="%d"
        ),
        "INSTALLMENT_AMT": Mapping(
            value="payments",
            allow_null=False,
            length=17,
            function_post_mapping="get_bank_installment_amount",
        ),
    }

    CONTRACT_MAPPING = {
        "CONTRACT_CODE": Mapping(
            value="loan.loan_xid",
            allow_null=False,
            length=15,
            function_post_mapping="get_contract_code",
        ),
        "CUSTOMER_ID": Mapping(
            value="customer.customer_xid",
            allow_null=False,
            length=10,
        ),
        "CUSTOMER_NAME": Mapping(value="detokenize_customer.fullname", allow_null=False, length=50),
        "MF_BRANCH_CODE": Mapping(
            value=MF_BRANCH,
            allow_null=False,
            length=4,
            is_hardcode=True,
        ),
        "MF_BRANCH_NAME": Mapping(
            value=MF_BRANCH,
            allow_null=False,
            length=4,
            is_hardcode=True,
        ),
        "SELLER_TYPE": Mapping(
            value=SELLER_TYPE,
            allow_null=False,
            length=4,
            is_hardcode=True,
        ),
        "EFFECTIVE_DATE": Mapping(
            value="loan.fund_transfer_ts_or_cdate",
            allow_null=False,
            length=10,
            output_format="%d-%m-%Y",
        ),
        "INITIAL_PRINCIPAL": Mapping(
            value="loan.loan_amount",
            allow_null=False,
            length=12,
        ),
        "GOODS_VALUE": Mapping(
            value="loan.loan_amount",
            allow_null=False,
            length=12,
        ),
        "MF_INITIAL_TENOR": Mapping(
            value="loan.loan_duration",
            allow_null=False,
            length=3,
        ),
        "MF_INSTALLMENT": Mapping(
            value="last_payment.due_amount",
            allow_null=False,
            length=12,
        ),
        "MF_INTEREST_RATE": Mapping(
            value="loan.interest_rate_monthly",
            allow_null=False,
            length=5,
            function_post_mapping="get_yearly_interest_rate",
        ),
        "ASSIGN_PRINCIPAL": Mapping(
            value="loan.loan_amount",
            allow_null=False,
            length=12,
        ),
        "BANK_PRINCIPAL": Mapping(
            value="loan.loan_amount",
            allow_null=False,
            length=12,
        ),
        "BANK_TENOR": Mapping(
            value="loan.loan_duration",
            allow_null=False,
            length=3,
        ),
        "FIRST_DUE_DATE": Mapping(
            value="first_payment.due_date", allow_null=False, length=10, output_format="%d-%m-%Y"
        ),
        "LAST_DUE_DATE": Mapping(
            value="last_payment.due_date", allow_null=False, length=10, output_format="%d-%m-%Y"
        ),
        "BANK_INTEREST_RATE": Mapping(
            value="channeling_loan_config",
            allow_null=False,
            length=5,
            function_post_mapping="get_bank_yearly_interest_rate",
        ),
        "BANK_INSTALLMENT": Mapping(
            value="payments",
            allow_null=False,
            length=12,
            function_post_mapping="get_bank_installment_amount",
        ),
        "BANK_INTEREST": Mapping(
            value="payments",
            allow_null=False,
            length=12,
            function_post_mapping="get_total_bank_interest_amount",
        ),
        "INSURANCE_AMOUNT": Mapping(
            value=INSURANCE_AMOUNT,
            allow_null=False,
            length=12,
            is_hardcode=True,
        ),
        "PREMIUM_PAYMENT": Mapping(
            value=PREMIUM_PAYMENT,
            allow_null=False,
            length=1,
            is_hardcode=True,
        ),
        "CREDIT_SCORING": Mapping(
            value=CREDIT_SCORING,
            allow_null=False,
            length=2,
            is_hardcode=True,
        ),
        "AGREEMENT_DATE": Mapping(
            value="loan.fund_transfer_ts_or_cdate",
            allow_null=False,
            length=10,
            output_format="%d-%m-%Y",
        ),
        "DOWN_PAYMENT": Mapping(
            value=DOWN_PAYMENT,
            allow_null=False,
            length=12,
            is_hardcode=True,
        ),
        "INSURANCE_COMPANY": Mapping(
            value=INSURANCE_COMPANY,
            length=10,
            is_hardcode=True,
        ),
        "AREA_BUSINESS": Mapping(
            value=AREA_BUSINESS,
            allow_null=False,
            length=10,
            is_hardcode=True,
        ),
        "PURPOSE_USAGE": Mapping(
            value=PURPOSE_USAGE,
            allow_null=False,
            length=10,
            is_hardcode=True,
        ),
        "CODE_IN_AREAR": Mapping(
            value=CODE_IN_AREAR,
            allow_null=False,
            length=1,
            is_hardcode=True,
        ),
        "GOODS_PRICE_INSURANCE": Mapping(
            value="loan.loan_amount",
            allow_null=False,
            length=12,
        ),
        "REMAINING CREDIT LIMIT": Mapping(
            value="account_limit.available_limit",
            allow_null=False,
            length=12,
        ),
        "CREDIT LIMIT": Mapping(
            value="account_limit.set_limit",
            allow_null=False,
            length=12,
        ),
        "FULL_CONTRACT_NUMBER": Mapping(
            value="loan.loan_xid",
            length=15,
            function_post_mapping="get_contract_code",
        ),
    }

    GOODS_INFO_MAPPING = {
        "CONTRACT_CODE": Mapping(
            value="loan.loan_xid",
            allow_null=False,
            length=15,
            function_post_mapping="get_contract_code",
        ),
        "COMMODITY_CATEGORY_CODE": Mapping(
            value=COMMODITY_CATEGORY_CODE,
            allow_null=False,
            length=30,
            is_hardcode=True,
        ),
        "PRODUCER": Mapping(
            value=PRODUCER,
            allow_null=False,
            length=30,
            is_hardcode=True,
        ),
        "CODE": Mapping(
            value="loan",
            allow_null=False,
            length=30,
            function_post_mapping="get_customer_loan_sequence",
        ),
        "TYPE_PF_GOODS": Mapping(
            value=TYPE_PF_GOODS,
            allow_null=False,
            length=5,
            is_hardcode=True,
        ),
        "TYPE_OF_GOODS": Mapping(
            value=TYPE_OF_GOODS,
            allow_null=False,
            length=51,
            is_hardcode=True,
        ),
        "PRICE_AMOUNT": Mapping(
            value="loan.loan_amount",
            allow_null=False,
            length=12,
        ),
    }

    INSTALLMENT_ELEMENT_MAPPING = {
        "RECORD_INDICATOR": Mapping(
            value=RECORD_INDICATOR.ljust(1),
            allow_null=False,
            is_padding_word=True,
            length=1,
            is_hardcode=True,
        ),
        "CONTRACT_NUMBER": Mapping(
            value="loan.loan_xid",
            allow_null=False,
            is_padding_word=True,
            length=17,
            function_post_mapping="get_contract_code",
        ),
        "DUE_DATE": Mapping(
            value="payment.due_date",
            allow_null=False,
            is_padding_word=True,
            length=10,
            output_format="%d-%m-%Y",
        ),
        "INSTALLMENT_NUMBER": Mapping(
            value="payment.payment_number",
            allow_null=False,
            is_padding_number=True,
            length=3,
        ),
        "PRINCIPAL_AMOUNT": Mapping(
            value="channeling_loan_payment.principal_amount",
            allow_null=False,
            is_padding_number=True,
            length=17,
        ),
        "INTEREST_AMOUNT": Mapping(
            value="channeling_loan_payment.interest_amount",
            allow_null=False,
            is_padding_number=True,
            length=17,
        ),
        "INSTALLMENT_AMOUNT": Mapping(
            value="channeling_loan_payment",
            allow_null=False,
            is_padding_number=True,
            length=17,
            function_post_mapping="get_installment_amount",
        ),
        "FILTER": Mapping(
            value=FILTER.ljust(118),
            allow_null=False,
            is_padding_word=True,
            length=118,
            is_hardcode=True,
        ),
    }


class DBSDisbursementDocumentConst:
    CONTENT_SEPARATOR = "|"

    REQUEST_FOLDER_NAME = "disbursement/request/"

    LOAN_INSTALLMENT_LIST_CONTENT_SEPARATOR = ""
    LOAN_INSTALLMENT_HEADER = "H{}"  # format datetime
    LOAN_INSTALLMENT_FOOTER = "T{}"  # format count of records excluding the header and trailer

    # first is the datetime format, second is the numerical order
    APPLICATION_FILENAME_FORMAT = "JFS_Q09_LOAN_APPL_{}{}.csv"
    CONTRACT_FILENAME_FORMAT = "JFS_Q09_CONTRACT_INFO_{}{}.txt"
    GOODS_INFO_FILENAME_FORMAT = "JFS_Q09_GOODS_INFO_{}{}.txt"
    LOAN_INSTALLMENT_LIST_FILENAME_FORMAT = "JFS_Q09_LOAN_SCH_{}{}.txt"


class DBSDisbursementApprovalConst:
    APPROVAL_FOLDER_NAME = "disbursement/approval/"

    LOAN_XID_COLUMN_HEADER = "Application_XID"
    APPROVAL_STATUS_COLUMN_HEADER = "disetujui"

    # first number is the data position, second number is the data length
    APPLICATION_STATUS_REPORT_DATA_COORDINATE = {
        LOAN_XID_COLUMN_HEADER: (64, 17),
        APPROVAL_STATUS_COLUMN_HEADER: (201, 10),
        "Org": (1, 3),
        "Type": (4, 3),
        "Application Number": (7, 13),
        "Application Status": (20, 1),
        "Reject Description": (24, 40),
        "DBS VisionPLUS Loan Account Number": (81, 19),
        "REJECT CODE": (165, 3),
    }

    APPLICATION_STATUS_MAPPING = {"Approved": "y", "Reject": "n"}


class DBSChannelingConst(object):
    APPROVAL_REMOTE_PATH_PER_FILE_TYPE = {
        ChannelingActionTypeConst.REPAYMENT: DBSRepaymentConst.APPROVAL_FOLDER_NAME,
        ChannelingActionTypeConst.RECONCILIATION: DBSReconciliationConst.APPROVAL_FOLDER_NAME,
        ChannelingActionTypeConst.DISBURSEMENT: DBSDisbursementApprovalConst.APPROVAL_FOLDER_NAME,
    }
