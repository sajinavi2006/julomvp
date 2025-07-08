from __future__ import division

import logging
import re
from typing import Dict, List

from babel.dates import format_date

from juloserver.channeling_loan.constants import (
    BSSChannelingConst,
    ChannelingLoanDatiConst,
    BSSMaritalStatusConst,
    BSSEducationConst,
    ChannelingStatusConst,
    ChannelingConst,
    FeatureNameConst as ChannelingFeatureNameConst,
    BSSDataField,
)
from juloserver.channeling_loan.models import ChannelingLoanCityArea
from juloserver.channeling_loan.clients import get_bss_channeling_client
from juloserver.channeling_loan.services.general_services import (
    get_channeling_loan_status,
    update_channeling_loan_status,
    success_channeling_process,
    recalculate_channeling_payment_interest,
    get_channeling_loan_configuration,
    is_channeling_lender_dashboard_active,
)

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    Payment,
    FeatureSetting,
)
from juloserver.julo.constants import FeatureNameConst

from juloserver.followthemoney.constants import (
    LenderTransactionTypeConst,
)
from juloserver.followthemoney.models import (
    LenderCurrent,
    LenderTransactionType,
)
from juloserver.ana_api.models import DynamicCheck
from juloserver.channeling_loan.utils import BSSCharacterTool

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def get_bss_refno(loan):
    return "%s%s" % (BSSChannelingConst.LOAN_PREFIX, str(loan.loan_xid).zfill(10))


def get_bss_refno_manual(loan):
    return "%s%s" % (BSSChannelingConst.LOAN_PREFIX_MANUAL, str(loan.loan_xid).zfill(10))


def construct_bss_disbursement_data(loan):
    application = loan.get_application
    error_check_required = checks_bss_required_field(loan, application)
    if error_check_required:
        logger.info({
            "action": 'channeling_loan.services.bss_services.construct_bss_disbursement_data',
            "message": str(error_check_required)
        })
        raise Exception(error_check_required)
    data = {
        "product": BSSChannelingConst.PRODUCT,
        "idcompany": BSSChannelingConst.COMPANYID,
        "description": "",
        "user": "",
        "hashcode": "",
    }
    data.update(construct_bss_customer_data(loan, application))
    data.update(construct_bss_loan_data(loan))
    data.update(construct_bss_collateral_data(loan))
    data.update(construct_bss_schedule_data(loan))
    return data


def checks_bss_required_field(loan, application):
    errors = []
    if not application.mobile_phone_1:
        errors.append("field mobileno is required")

    if not application.monthly_income:
        errors.append("field grossincome is required")

    return errors


def construct_bss_customer_data(loan, application) -> Dict[str, str]:
    data = {
        "customerdata[refnocustid]": loan.loan_xid,
        "customerdata[din]": "",
        "customerdata[custtype]": "1",
        BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('fullname'): application.fullname,
        BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('custname'): application.fullname,
        "customerdata[title]": "",
        "customerdata[email]": application.email,
        "customerdata[custaddress]": application.full_address,
        "customerdata[custrt]": "00",
        "customerdata[custrw]": "00",
        "customerdata[custkel]": application.address_kelurahan,
        "customerdata[custkec]": application.address_kecamatan,
        "customerdata[custcity]": application.address_kabupaten,
        "customerdata[custprov]": application.address_provinsi,
        BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('zipcode'): application.address_kodepos,
        "customerdata[custdati]": change_city_to_dati_code(
            application.address_kabupaten
        ),
        "customerdata[idtype]": "1",
        "customerdata[idnumber]": application.ktp,
        "customerdata[idexpired]": "2999-12-31",
        "customerdata[gender]": "1" if application.gender == "Pria" else "2",
        "customerdata[maritalstatus]": BSSMaritalStatusConst.LIST[application.marital_status],
        BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('birthdate'): format_date(
            application.dob, "yyyy-MM-dd", locale="id_ID"
        ),
        BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('birthplace'): (application.birth_place),
        "customerdata[birthdati]": change_city_to_dati_code(application.address_kabupaten)
        if application.address_kabupaten
        else "",
        "customerdata[worksince]": format_date(
            application.job_start, "yyyy-MM-dd", locale="id_ID"
        ),
        "customerdata[workradius]": "",
        "customerdata[employeests]": "",
        "customerdata[contractend]": "",
        "customerdata[lasteducation]": get_bss_education_mapping().get(
            application.last_education, ""
        ),
        "customerdata[economycode]": "004190",
        "customerdata[debiturcode]": "9000",
        BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('mothername'): (
            application.customer_mother_maiden_name
        ),
        "customerdata[npwp]": "0",
        "customerdata[homestatus]": "",
        "customerdata[livedsince]": format_date(
            application.occupied_since, "yyyy-MM-dd", locale="id_ID"
        ),
        "customerdata[phonearea]": 0,
        BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('phoneno'): application.mobile_phone_1 or 0,
        BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('mobileno'): application.mobile_phone_1,
        "customerdata[dependent]": application.dependent,
        "customerdata[grossincome]": application.monthly_income,
        "customerdata[expenses]": application.monthly_expenses,
        "customerdata[sameidhomeaddr]": "0",
        "customerdata[custaddresshome]": application.full_address,
        "customerdata[custrthome]": "00",
        "customerdata[custrwhome]": "00",
        "customerdata[custkelhome]": application.address_kelurahan,
        "customerdata[custkechome]": application.address_kecamatan,
        "customerdata[custcityhome]": application.address_kabupaten,
        "customerdata[custprovhome]": application.address_provinsi,
        "customerdata[custziphome]": application.address_kodepos,
        "customerdata[custdatihome]": change_city_to_dati_code(
            application.address_kabupaten
        ),
        "customerdata[spousename]": application.spouse_name,
        "customerdata[spousebirthdate]": "",
        "customerdata[spousebirthplace]": "",
        "customerdata[spouseidtype]": "1",
        "customerdata[spouseidnumber]": "",
        "customerdata[spousephoneno]": "",
        "customerdata[spousemobileno]": "",
        "customerdata[spouseoffice]": "",
        "customerdata[spouseoffinephone]": "",
        "customerdata[relativestype]": "",
        "customerdata[relativesname]": application.kin_name or application.spouse_name,
        "customerdata[custaddressrel]": "NA",
        "customerdata[custrtrel]": "",
        "customerdata[custrwrel]": "",
        "customerdata[custkelrel]": "",
        "customerdata[custkecrel]": "",
        "customerdata[custcityrel]": "",
        "customerdata[custprovrel]": "",
        "customerdata[custziprel]": "",
        "customerdata[phonenorel]": "",
        "customerdata[companyname]": "",
        "customerdata[companyaddr]": "",
        "customerdata[companycity]": "",
        "customerdata[companyzip]": "",
        "customerdata[companyphone]": "",
        "customerdata[deedno]": "",
        "customerdata[deeddate]": "",
        "customerdata[corporatetype]": "",
        "customerdata[jobid]": "099",
        "customerdata[jobtitleid]": "69",
        "customerdata[countryid]": "ID",
        "customerdata[branchcode]": "JULO-001",
        "customerdata[targetmarket]": "1",
    }

    # replace special characters for specific fields
    replaced_data = replace_special_chars_for_fields(
        data=data,
        fields=[*BSSDataField.customer_address()],
    )
    return replaced_data


def replace_special_chars_for_fields(data: Dict[str, str], fields: List[str]) -> Dict[str, str]:
    """
    For BSS: replace values of specified fields with accepted chars
    """
    tool = BSSCharacterTool()
    for field in fields:
        value = data[field]
        data[field] = tool.replace_bad_chars(value)

    return data


def construct_bss_loan_data(loan):
    channeling_loan_config = get_channeling_loan_configuration(ChannelingConst.BSS)
    first_payment = Payment.objects.filter(loan=loan).order_by('due_date').first()
    effectife_rate = BSSChannelingConst.EFFECTIVERATE
    if channeling_loan_config:
        interest_rate = channeling_loan_config["general"]["INTEREST_PERCENTAGE"]
        risk_premium_rate = channeling_loan_config["general"]["RISK_PREMIUM_PERCENTAGE"]
        effectife_rate = interest_rate + risk_premium_rate

    return {
        "loandata[refnocustid]": loan.loan_xid,
        "loandata[refno]": get_bss_refno(loan),
        "loandata[objectvalue]": loan.loan_amount,
        "loandata[principaltotal]": loan.loan_amount,
        "loandata[tenor]": loan.loan_duration,
        "loandata[tenorunit]": "3",
        "loandata[loantype]": "0",
        "loandata[effectiverate]": effectife_rate,
        "loandata[installment]": loan.installment_amount,
        "loandata[firstinstdate]": format_date(
            first_payment.due_date, 'yyyy-MM-dd', locale='id_ID'),
        "loandata[admfee]": loan.product.origination_fee_pct,
        "loandata[inscode]": 1,
        "loandata[inspremi]": 0,
        "loandata[insonloan]": 0,
        "loandata[installmenttype]": 103,
        "loandata[branchcode]": "ID0010009",
        "loandata[typeofuseid]": "3",
        "loandata[orientationofuseid]": "9",
        "loandata[debiturcatid]": "99",
        "loandata[portfoliocatid]": "36",
        "loandata[credittypeid]": "20",
        "loandata[creditattributeid]": "9",
        "loandata[creditcategoryid]": "99",
        "loandata[fincat]": "000",
        "loandata[creditdistrib]": "3",
        "loandata[idcompany]": BSSChannelingConst.COMPANYID,
        "loandata[interestratecust]": "30",
        "loandata[disbursedate]": format_date(loan.fund_transfer_ts, 'yyyy-MM-dd', locale='id_ID'),
        "loandata[deposit]": 0,
    }


def construct_bss_collateral_data(loan):
    return {
        "collateraldata[refno]": get_bss_refno(loan),
        "collateraldata[productcode]": "000",
        "collateraldata[merkcode]": "0",
        "collateraldata[modelcode]": "0",
        "collateraldata[collateralno]": "0",
        "collateraldata[collateraladdress]": "NA",
        "collateraldata[collateralname]": "NA",
        "collateraldata[engineno]": "NA",
        "collateraldata[chassisno]": "NA",
        "collateraldata[collateralyear]": "0",
        "collateraldata[buildyear]": "0",
        "collateraldata[condition]": "0",
        "collateraldata[color]": "NA",
        "collateraldata[collateralkind]": "NA",
        "collateraldata[collateralpurpose]": "NA",
        "collateraldata[policeno]": "NA",
        "collateraldata[surveydate]": "9999-12-31",
        "collateraldata[bindtypecode]": "NA",
        "collateraldata[collateraltypecode]": "NA",
        "collateraldata[collateralvalue]": "0",
        "collateraldata[owncollateral]": "00",
    }


def construct_bss_schedule_data(loan, is_manual=False):
    payments = loan.payment_set.not_paid_active().order_by('payment_number')
    new_interests = recalculate_channeling_payment_interest(loan, ChannelingConst.BSS)
    data = {}
    refno = get_bss_refno(loan)
    if is_manual:
        refno = get_bss_refno_manual(loan)
    for index, payment in enumerate(payments):
        key = "schedule[{}]".format(index)
        data.update(
            {
                "%s[refno]" % key: refno,
                "%s[period]" % key: payment.payment_number,
                "%s[duedate]" % key: format_date(payment.due_date, 'yyyy-MM-dd', locale='id_ID'),
                "%s[principal]" % key: payment.installment_principal,
                "%s[interest]" % key: new_interests[payment.id],
                "%s[principalpaid]" % key: "0",
                "%s[interestpaid]" % key: "0",
                "%s[penaltypaid]" % key: "0",
                "%s[paidsts]" % key: "0",
                "%s[paiddate]" % key: "",
                "%s[paidtxndate]" % key: "",
            }
        )
    return data


def change_city_to_dati_code(city):
    channeling_city_area = ChannelingLoanCityArea.objects.filter(city_area=city).first()

    if channeling_city_area:
        # return selected city
        return channeling_city_area.city_area_code

    # case selected city not found, return outside indo (default 9999)
    default_channeling_city_area = ChannelingLoanCityArea.objects.filter(
        city_area=ChannelingLoanDatiConst.DEFAULT_NOT_FOUND_AREA
    ).first()

    return (
        default_channeling_city_area.city_area_code
        if default_channeling_city_area
        else ChannelingLoanDatiConst.DEFAULT_NOT_FOUND_CODE
    )


def reconstruct_response_format(response):
    result = response['data'].get('result', {}) if response.get('data') else {}
    error = response.get('error', {})
    status = response.get('status', BSSChannelingConst.NOT_OK_STATUS)
    return status, result, error


def validate_bss_disbursement_data(bss_disbursement_data):
    # make sure kodepos is not 00000 and theres no number in birthplace
    zip_code = bss_disbursement_data.get(BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('zipcode'))
    birth_place = bss_disbursement_data.get(
        BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('birthplace')
    )
    if zip_code == "00000":
        return "Zip code cannot be 00000"

    if birth_place and re.search(r'\d', birth_place):
        return "Birthplace cannot contain number"

    return


def sanitize_bss_disbursement_data(bss_disbursement_data):
    regex = "[^A-Za-z0-9 ]+"
    for sanitize in BSSChannelingConst.BSS_SANITIZE_DATA:
        key = BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get(sanitize)
        if key in bss_disbursement_data:
            bss_disbursement_data[key] = re.sub(regex, '', str(bss_disbursement_data[key]))

    return


def send_loan_for_channeling_to_bss(loan, channeling_loan_config):
    if not loan:
        return ChannelingStatusConst.FAILED, "Loan not found", ChannelingConst.DEFAULT_INTERVAL

    general_channeling_config = channeling_loan_config['general']
    lender = LenderCurrent.objects.get_or_none(lender_name=general_channeling_config['LENDER_NAME'])
    if not lender:
        return ChannelingStatusConst.FAILED, "Lender not found", ChannelingConst.DEFAULT_INTERVAL

    transaction_type = LenderTransactionType.objects.get_or_none(
        transaction_type=LenderTransactionTypeConst.CHANNELING)
    if not transaction_type:
        return (
            ChannelingStatusConst.FAILED,
            "Channeling transaction not found",
            ChannelingConst.DEFAULT_INTERVAL
        )

    if loan.lender and loan.lender.lender_name in general_channeling_config['EXCLUDE_LENDER_NAME']:
        return ChannelingStatusConst.FAILED, "Lender excluded", ChannelingConst.DEFAULT_INTERVAL

    lender_balance = lender.lenderbalancecurrent
    if not lender_balance:
        return (
            ChannelingStatusConst.FAILED,
            "Lender balance not found",
            ChannelingConst.DEFAULT_INTERVAL
        )

    if lender_balance.available_balance < loan.loan_amount:
        return (
            ChannelingStatusConst.FAILED,
            "Lender balance is less than loan amount",
            ChannelingConst.DEFAULT_INTERVAL
        )

    application = loan.get_application
    dati_code = change_city_to_dati_code(application.address_kabupaten)
    if dati_code == "9999":
        return (
            ChannelingStatusConst.FAILED,
            "City %s not found" % application.address_kabupaten,
            ChannelingConst.DEFAULT_INTERVAL
        )

    """
    Status have to be PENDING and then updated to PROCESS
    but when BSS lender dashboard is active, status have to be PROCESS
    This happen because status already changed to PROCESS in lender dashboard
    """
    is_bss_lender_dashboard_enabled = is_channeling_lender_dashboard_active(ChannelingConst.BSS)
    current_bss_status = ChannelingStatusConst.PENDING
    if is_bss_lender_dashboard_enabled:
        current_bss_status = ChannelingStatusConst.PROCESS

    channeling_loan_status = get_channeling_loan_status(loan, current_bss_status)
    if not channeling_loan_status:
        return (
            ChannelingStatusConst.FAILED,
            "Channeling loan status data missing",
            ChannelingConst.DEFAULT_INTERVAL
        )

    bss_disbursement_data = construct_bss_disbursement_data(loan)
    # validate any custom constrain related to application data here
    error_disbursement_data = validate_bss_disbursement_data(bss_disbursement_data)
    if error_disbursement_data:
        update_channeling_loan_status(
            channeling_loan_status.id,
            new_status=ChannelingStatusConst.FAILED,
            change_reason=error_disbursement_data,
        )
        return (
            ChannelingStatusConst.FAILED,
            error_disbursement_data,
            ChannelingConst.DEFAULT_INTERVAL,
        )

    # sanitize the data before it sent to BSS
    sanitize_bss_disbursement_data(bss_disbursement_data)

    # change status to PROCESS before making request
    if not is_bss_lender_dashboard_enabled:
        update_channeling_loan_status(channeling_loan_status.id, ChannelingStatusConst.PROCESS)

    # make request to bss
    bss_channeling_client = get_bss_channeling_client()
    channeling_response = bss_channeling_client.send_request(
        "disburse", "post", loan, bss_disbursement_data
    )

    status, result, error = reconstruct_response_format(channeling_response)
    if error:
        if status == BSSChannelingConst.NOT_OK_STATUS:
            retry_channeling_feature = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.BSS_CHANNELING_RETRY, is_active=True,
            ).last()
            if retry_channeling_feature:
                async_interval = retry_channeling_feature.parameters["minutes"]
                return ChannelingStatusConst.RETRY, "Continue retry process", async_interval
            update_channeling_loan_status(
                channeling_loan_status.id, ChannelingStatusConst.FAILED, change_reason=error
            )
        return ChannelingStatusConst.FAILED, error, ChannelingConst.DEFAULT_INTERVAL

    if status == BSSChannelingConst.OK_STATUS:
        if result['responseCode'] == BSSChannelingConst.SUCCESS_STATUS_CODE:
            channeling_proccess_status, message = success_channeling_process(
                loan, lender, transaction_type, loan.loan_amount,
                ChannelingStatusConst.PROCESS, ChannelingStatusConst.SUCCESS
            )
            if channeling_proccess_status == ChannelingStatusConst.FAILED:
                return channeling_proccess_status, message, ChannelingConst.DEFAULT_INTERVAL

        elif result['responseCode'] in BSSChannelingConst.FAILED_STATUS_CODES:
            update_channeling_loan_status(
                channeling_loan_status.id, ChannelingStatusConst.FAILED,
                change_reason=result.get('responseDescription', '')
            )

    return ChannelingStatusConst.SUCCESS, result, ChannelingConst.DEFAULT_INTERVAL


def check_disburse_transaction(loan, retry_count):
    channeling_loan_config = get_channeling_loan_configuration(ChannelingConst.BSS)
    if not channeling_loan_config:
        return (
            ChannelingStatusConst.FAILED,
            "Channeling configuration not set",
            ChannelingConst.DEFAULT_INTERVAL
        )

    general_config = channeling_loan_config['general']

    retry_channeling_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BSS_CHANNELING_RETRY
    ).last()
    if not retry_channeling_feature:
        return (
            ChannelingStatusConst.FAILED,
            "Unconfigurize retry feature",
            ChannelingConst.DEFAULT_INTERVAL
        )

    if not retry_channeling_feature.is_active:
        return ChannelingStatusConst.FAILED, "Inactive feature", ChannelingConst.DEFAULT_INTERVAL

    if retry_count > retry_channeling_feature.parameters["max_retry_count"]:
        return ChannelingStatusConst.FAILED, "Retry limit reach", ChannelingConst.DEFAULT_INTERVAL

    lender = LenderCurrent.objects.get_or_none(lender_name=general_config['LENDER_NAME'])
    if not lender:
        return ChannelingStatusConst.FAILED, "Lender not found", ChannelingConst.DEFAULT_INTERVAL

    transaction_type = LenderTransactionType.objects.get_or_none(
        transaction_type=LenderTransactionTypeConst.CHANNELING)
    if not transaction_type:
        return (
            ChannelingStatusConst.FAILED,
            "Channeling transaction not found",
            ChannelingConst.DEFAULT_INTERVAL
        )

    if loan.lender and loan.lender.lender_name in general_config['EXCLUDE_LENDER_NAME']:
        return ChannelingStatusConst.FAILED, "Lender excluded", ChannelingConst.DEFAULT_INTERVAL

    data = {
        "refno": get_bss_refno(loan),
        "trxtype": "DS",
        "hashcode": "",
    }
    bss_channeling_client = get_bss_channeling_client()
    channeling_response = bss_channeling_client.send_request(
        "checkTransaction", "post", loan, data)

    interval = retry_channeling_feature.parameters["minutes"]
    status, result, error = reconstruct_response_format(channeling_response)
    if error:
        if status == BSSChannelingConst.NOT_OK_STATUS:
            return ChannelingStatusConst.RETRY, "Continue retry process", interval
        return ChannelingStatusConst.FAILED, error, ChannelingConst.DEFAULT_INTERVAL

    if status == BSSChannelingConst.OK_STATUS:
        if result['responseCode'] == BSSChannelingConst.ONPROGRESS_STATUS_CODE:
            return ChannelingStatusConst.RETRY, result['responseDescription'], interval

        if result['responseCode'] == BSSChannelingConst.SUCCESS_STATUS_CODE:
            channeling_proccess_status, message = success_channeling_process(
                loan, lender, transaction_type, loan.loan_amount,
                ChannelingStatusConst.PROCESS, ChannelingStatusConst.SUCCESS
            )
            if channeling_proccess_status == ChannelingStatusConst.FAILED:
                return channeling_proccess_status, message, ChannelingConst.DEFAULT_INTERVAL
    return ChannelingStatusConst.SUCCESS, result['responseCode'], ChannelingConst.DEFAULT_INTERVAL


def get_bss_education_mapping(is_manual=None):
    if is_manual:
        feature_setting = FeatureSetting.objects.filter(
            feature_name=ChannelingFeatureNameConst.BSS_MANUAL_CHANNELING_EDUCATION_MAPPING,
            is_active=True,
        ).last()
        return (
            feature_setting.parameters
            if feature_setting
            else BSSEducationConst.LIST_CHANNELING_MANUAL
        )
    feature_setting = FeatureSetting.objects.filter(
        feature_name=ChannelingFeatureNameConst.BSS_CHANNELING_EDUCATION_MAPPING,
        is_active=True,
    ).last()
    return feature_setting.parameters if feature_setting else BSSEducationConst.LIST


def is_holdout_users_from_bss_channeling(application_id):
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.HOLDOUT_USERS_FROM_BSS_CHANNELING, is_active=True
    ).exists()
    if fs:
        return DynamicCheck.objects.filter(
            application_id=application_id, is_okay=False, is_holdout=True
        ).exists()

    return False


def check_transfer_out_status(loan, retry_count):
    retry_channeling_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BSS_CHANNELING_RETRY
    ).last()
    if not retry_channeling_feature:
        return (
            ChannelingStatusConst.FAILED,
            "Unconfigurize retry feature",
            ChannelingConst.DEFAULT_INTERVAL
        )

    if not retry_channeling_feature.is_active:
        return ChannelingStatusConst.FAILED, "Inactive feature", ChannelingConst.DEFAULT_INTERVAL

    if retry_count > retry_channeling_feature.parameters["max_retry_count"]:
        return ChannelingStatusConst.FAILED, "Retry limit reach", ChannelingConst.DEFAULT_INTERVAL

    data = {
        "refno": get_bss_refno(loan),
        "trxtype": "TO",
        "hashcode": "",
    }
    bss_channeling_client = get_bss_channeling_client()
    channeling_response = bss_channeling_client.send_request(
        "checkTransaction", "post", loan, data)

    interval = retry_channeling_feature.parameters["minutes"]
    status, result, error = reconstruct_response_format(channeling_response)
    if error:
        if status == BSSChannelingConst.NOT_OK_STATUS:
            return ChannelingStatusConst.RETRY, "Continue retry process", interval
        return ChannelingStatusConst.FAILED, error, ChannelingConst.DEFAULT_INTERVAL

    if status == BSSChannelingConst.OK_STATUS:
        if result['responseCode'] == BSSChannelingConst.TRANSFER_OUT_PENDING_STATUS_CODE:
            return ChannelingStatusConst.RETRY, result['responseDescription'], interval

        if result['responseCode'] == BSSChannelingConst.TRANSFER_OUT_SUCCESS_STATUS_CODE:
            return (
                ChannelingStatusConst.SUCCESS,
                result['responseDescription'],
                ChannelingConst.DEFAULT_INTERVAL
            )

    return (
        ChannelingStatusConst.FAILED,
        result['responseDescription'],
        ChannelingConst.DEFAULT_INTERVAL
    )
