from typing import List, Tuple
from juloserver.julo.models import (
    Application, 
    ApplicationFieldChange, 
    Customer,
    Skiptrace,
    transaction,
)
from juloserver.apiv1.models import logger
from juloserver.account.models import Account
from juloserver.julo.utils import format_valid_e164_indo_phone_number

class RemovePhoneNumberParamDTO(object):
    def __init__(self, account_id: str, phone_number: str) -> None:
        self.account_id = account_id
        self.phone_number = phone_number

class RemovePhoneNumberResultDTO(object):
    def __init__(self, account_id: str, phone_number: str) -> None:
        self.account_id = account_id
        self.phone_number = phone_number
        self.status = ''
        self.reason = ''
        self.source_deleted_in_app = ''
        self.source_deleted_in_skiptrace = ''

def remove_phone_number(data: List[RemovePhoneNumberParamDTO]) -> List[RemovePhoneNumberResultDTO]:
    logger.info({
        "function_name": "remove_phone_number",
        "action": "start process remove phone number",
    })

    res = []
    res_keys = set()

    for datum in data:
        curr_account_id = datum.account_id
        curr_phone_number = datum.phone_number
        curr_res = RemovePhoneNumberResultDTO(curr_account_id, curr_phone_number)

        if not curr_account_id.isdigit():
            curr_res.status = "Failed"
            curr_res.reason = "Account id format is not valid"
            res.append(curr_res)
            continue

        curr_key = compose_key([curr_account_id, curr_phone_number])
        if curr_key in res_keys:
            curr_res.status = "Failed"
            curr_res.reason = "Duplicated"
            res.append(curr_res)
            continue
        else:
            res_keys.add(curr_key)

        try:
            curr_account = Account.objects.get_or_none(pk = curr_account_id)
            if curr_account == None:
                curr_res.status = "Failed"
                curr_res.reason = "Account with given account id not found"
                res.append(curr_res)
                continue

            curr_app = Application.objects.filter(account_id = curr_account_id).last()

            curr_phone_number = valid_phone_or_empty(curr_phone_number)
            if curr_phone_number == "":
                curr_res.status = "Failed"
                curr_res.reason = "Phone format is not valid"
                res.append(curr_res)
                continue
            if valid_phone_or_empty(curr_app.mobile_phone_1) == curr_phone_number:
                curr_res.status = "Failed"
                curr_res.reason = "Not change the number because detected as app.mobile_phone_1"
                res.append(curr_res)
                continue
            
            app_source, skiptrace_source = remove_phone_number_action(curr_account_id, curr_phone_number)
            if(app_source == "" and skiptrace_source == ""):
                curr_res.status = "Failed"
                curr_res.reason = "Given phone number not found in application and skiptrace table"
                res.append(curr_res)
                continue
            
            curr_res.status = "Success"
            curr_res.source_deleted_in_app = app_source
            curr_res.source_deleted_in_skiptrace = skiptrace_source
            res.append(curr_res)
        except Exception as e:
            curr_res.status = "Failed"
            curr_res.reason = e
            res.append(curr_res)

    logger.info({
        "function_name": "remove_phone_number",
        "action": "finish process remove phone number",
    })
    
    return res

def remove_phone_number_action(account_id: str, phone_number: str) -> Tuple[str, str]:
    logger.info({
        "function_name": "remove_phone_number_action",
        "action": "start process remove phone number action",
    })

    app = Application.objects.filter(account_id = account_id).last()
    app_source_deleted = remove_phone_number_application(app, phone_number)
    skiptrace_source_deleted = remove_phone_number_in_skiptrace(app.customer_id, phone_number)

    logger.info({
        "function_name": "remove_phone_number_action",
        "action": "finish process remove phone number action",
    })

    return (app_source_deleted, skiptrace_source_deleted)

def remove_phone_number_application(app: Application, phone_number: str) -> str:
    cust_id = app.customer_id

    logger_data = {'customer_id': cust_id, 'phone_number': phone_number}
    logger.info({
        "function_name": "remove_phone_number_application",
        "action": "start process remove customer phone number in app table",
        "data": logger_data,
    })

    app_source_deleted = ""
    temp_log = []

    # Remove mobile_phone_2.
    app_mp_2 = app.mobile_phone_2
    if app_mp_2 and valid_phone_or_empty(app_mp_2) == phone_number:
        app.update_safely(mobile_phone_2 = None)

        app_source_deleted = "mobile_phone_2"
        temp_log.append(app_source_deleted)
        logger_data["app_source_deleted"] = app_source_deleted

        logger.info({
            "function_name": "remove_phone_number_application",
            "action": "success remove {}".format(app_source_deleted),
            "data": logger_data,
        }) 

    # Remove company_phone_number.
    app_cpn = app.company_phone_number
    if app_cpn and valid_phone_or_empty(app_cpn) == phone_number:
        app.update_safely(company_phone_number = None)

        app_source_deleted = "company_phone_number"
        temp_log.append(app_source_deleted)
        logger_data["app_source_deleted"] = app_source_deleted

        logger.info({
            "function_name": "remove_phone_number_application",
            "action": "success remove {}".format(app_source_deleted),
            "data": logger_data,
        }) 

    # Remove close_kin_mobile_phone.
    app_close_kin_mp = app.close_kin_mobile_phone
    if app_close_kin_mp and valid_phone_or_empty(app_close_kin_mp) == phone_number:
        app.update_safely(close_kin_mobile_phone = None)

        app_source_deleted = "close_kin_mobile_phone"
        temp_log.append(app_source_deleted)
        logger_data["app_source_deleted"] = app_source_deleted

        logger.info({
            "function_name": "remove_phone_number_application",
            "action": "success remove {}".format(app_source_deleted),
            "data": logger_data,
        }) 

    # Remove spouse_mobile_phone.
    app_spouse_mp = app.spouse_mobile_phone
    if app_spouse_mp and valid_phone_or_empty(app_spouse_mp) == phone_number:
        app.update_safely(spouse_mobile_phone = None)

        app_source_deleted = "spouse_mobile_phone"
        temp_log.append(app_source_deleted)
        logger_data["app_source_deleted"] = app_source_deleted

        logger.info({
            "function_name": "remove_phone_number_application",
            "action": "success remove {}".format(app_source_deleted),
            "data": logger_data,
        }) 

    # Remove kin_mobile_phone.
    app_kin_mp = app.kin_mobile_phone
    if app_kin_mp and valid_phone_or_empty(app_kin_mp) == phone_number:
        app.update_safely(kin_mobile_phone = None)

        app_source_deleted = "kin_mobile_phone"
        temp_log.append(app_source_deleted)
        logger_data["app_source_deleted"] = app_source_deleted

        logger.info({
            "function_name": "remove_phone_number_application",
            "action": "success remove {}".format(app_source_deleted),
            "data": logger_data,
        }) 

    if app_source_deleted != "":
        logger.info({
            "function_name" : "remove_phone_number_application",
            "action": "success remove phone number in app table",
            "data": logger_data,
        })
        with transaction.atomic():
            ApplicationFieldChange.objects.create(
                application = app,
                field_name = app_source_deleted,
                old_value = phone_number,
                new_value = "",
            )
    else:
        logger.info({
            "function_name" : "remove_phone_number_application",
            "action": "fail remove phone number in app table because data not exist",
            "data": logger_data
        })

    logger.info({
        "function_name": "remove_phone_number_application",
        "action": "finish process remove customer phone number in app table",
        "data": logger_data
    })

    return app_source_deleted

def remove_phone_number_in_skiptrace(cust_id, phone_number):
    logger_data = {'customer_id': cust_id, 'phone_number': phone_number}
    logger.info({
        "function_name": "remove_phone_number_in_skiptrace",
        "action": "start process remove customer phone number in skiptrace table",
        "data": logger_data,
    })

    skiptrace_source_deleted = ""
    try:
        skList = Skiptrace.objects.filter(customer_id = cust_id)
        for sk in skList:
            if sk.phone_number == None or sk.contact_source == "mobile_phone_1":
                continue

            skiptrace_phone_number = valid_phone_or_empty(str(sk.phone_number.national_number))
            if phone_number == skiptrace_phone_number:
                skiptrace_source_deleted = sk.contact_source

                sk.phone_number = None
                sk.contact_name = None
                sk.contact_source = None
                sk.phone_operator = None
                sk.effectiveness = 0
                sk.frequency = 0
                sk.recency = None
                sk.save()

                logger_data["skiptrace_source_deleted"] = skiptrace_source_deleted
                logger.info({
                    "function_name": "remove_phone_number_in_skiptrace",
                    "action": "success remove cust number in skiptrace table",
                    "data": logger_data,
                })
    except Exception as e:
        skiptrace_source_deleted = ""
        
        logger_data["skiptrace_source_deleted"] = skiptrace_source_deleted
        logger.error({
            "function_name": "remove_phone_number_in_skiptrace",
            "message": "failed remove cust number in skiptrace table because already removed or not yet created",
            "data": logger_data,
            "error": e
        })
    
    logger.info({
        "function_name": "remove_phone_number_in_skiptrace",
        "action": "finish process remove customer phone number in skiptrace table",
        "data": logger_data,
    })

    return skiptrace_source_deleted

def compose_key(arr: List[str]) -> str:
    result = ""
    for index in range(0, len(arr)):
        temp_key = str(arr[index])
        result += temp_key
        if index != len(arr) - 1:
            result += " - "

    return result

def valid_phone_or_empty(phone_number: str):
    try:
        if not phone_number.isdigit():
            raise Exception("phone number contains another char except number")
            
        return format_valid_e164_indo_phone_number(phone_number)
    except:
        return ""
