from juloserver.julolog.julolog import JuloLog
from juloserver.julo.services import process_application_status_change
from juloserver.julo.utils import format_e164_indo_phone_number, execute_after_transaction_safely
from juloserver.julo.utils import format_valid_e164_indo_phone_number
from django.db import transaction
from juloserver.julo.models import (
    Customer,
    Application,
    Skiptrace,
    ApplicationNote,
    ApplicationFieldChange,
    CustomerFieldChange,
    AuthUserFieldChange,
)

from juloserver.grab.models import GrabCustomerData
from juloserver.julo.statuses import ApplicationStatusCodes

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from juloserver.disbursement.models import NameBankValidation
from juloserver.pre.services.common import track_agent_retrofix
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import tokenize_pii_data, prepare_pii_event

logger = JuloLog(__name__)

grab_graveyard_statuses = {
    ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,  # 106
    ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,  # 136
    ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,  # 139
    ApplicationStatusCodes.APPLICATION_DENIED,  # 135
    ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,  # 137
    ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,  # 111
    ApplicationStatusCodes.OFFER_EXPIRED,  # 143
    ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,  # 171
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD  # 133
}

def _valid_phone_or_empty(phone):
    try:
        return format_valid_e164_indo_phone_number(phone)
    except Exception:
        return ""


def _create_key(input_array):
    result = ""
    for index in range(len(input_array)):
        temp_key = str(input_array[index])
        result += temp_key
        if index != len(input_array) - 1:
            result += " - "
    return result


def _get_summary_from_result(result):
    summary = {}
    for keys, logs in result.items():
        for log in logs:
            if not (log in summary):
                summary[log] = 1
            else:
                summary[log] += 1
    return summary


def _change_username(cust_id, new_value, type):
    # if there is no exception, change it !
    cust = Customer.objects.get(pk=cust_id)
    auth_user = User.objects.get(pk=cust.user_id)
    old_value = auth_user.username

    if type == 'email' and "@" not in old_value:
        return
    if type == 'mobile_phone_1' and not _valid_phone_or_empty(old_value):
        return

    auth_user.username = new_value
    auth_user.save(update_fields=['username'])
    auth_user_field_change = _create_history_auth_user(
        auth_user, cust, "username", old_value, new_value
    )

    return auth_user_field_change


def _check_duplicate_username(current_user_id, new_value):
    # validate if there is any duplicate
    user_with_usernames = User.objects.filter(username=new_value).exclude(id=current_user_id)
    if user_with_usernames:
        all_user_id_with_this_username = ""
        for user_with_username in user_with_usernames:
            all_user_id_with_this_username += str(user_with_username.id) + " , "
        raise Exception(
            "This fix cannot be done, because this user ("
            + all_user_id_with_this_username
            + ") have this username : "
            + str(new_value)
        )


def _change_application_data(app_id, data_changes, application_note=None, prevent_duplicate=True):
    with transaction.atomic():
        app = Application.objects.get(pk=app_id)
        cust = app.customer

        is_allow_to_token_pii_data = True if app.is_julo_one_or_starter() else False

        # change device_id
        if "device_id" in data_changes:
            old_device_id = app.device_id
            new_device_id = data_changes["device_id"]
            app.update_safely(device_id=new_device_id)
            _create_history_application(app, "device_id", old_device_id, new_device_id)

        if "account_id" in data_changes:
            old_account_id = app.account_id
            new_account_id = data_changes["account_id"]
            app.update_safely(account_id=new_account_id)
            _create_history_application(app, "account_id", old_account_id, new_account_id)

        # change onboarding_id
        if "onboarding_id" in data_changes:
            old_onboarding_id = app.onboarding_id
            new_onboarding_id = data_changes["onboarding_id"]
            app.update_safely(onboarding_id=new_onboarding_id)
            _create_history_application(app, "onboarding_id", old_onboarding_id, new_onboarding_id)

        # change workflow_id
        if "workflow_id" in data_changes:
            old_workflow_id = app.workflow_id
            new_workflow_id = data_changes["workflow_id"]
            app.update_safely(workflow_id=new_workflow_id)
            _create_history_application(app, "workflow_id", old_workflow_id, new_workflow_id)

        # change bank name
        if "bank_name" in data_changes:
            old_bank_name = app.bank_name
            new_bank_name = data_changes["bank_name"]
            app.update_safely(bank_name=new_bank_name)
            _create_history_application(app, "bank_name", old_bank_name, new_bank_name)

        if "bank_account_number" in data_changes:
            old_bank_account_number = app.bank_account_number
            new_bank_account_number = data_changes["bank_account_number"]
            app.update_safely(bank_account_number=new_bank_account_number)
            _create_history_application(
                app, "bank_account_number", old_bank_account_number, new_bank_account_number
            )

        if "payday" in data_changes:
            old_payday = app.payday
            new_payday = data_changes["payday"]
            app.update_safely(payday=new_payday)
            _create_history_application(app, "payday", old_payday, new_payday)

        if "marital_status" in data_changes:
            old_marital_status = app.marital_status
            new_marital_status = data_changes["marital_status"]
            app.update_safely(marital_status=new_marital_status)
            _create_history_application(
                app, "marital_status", old_marital_status, new_marital_status
            )

        if "company_name" in data_changes:
            old_company_name = app.company_name
            new_company_name = data_changes["company_name"]
            app.update_safely(company_name=new_company_name)
            _create_history_application(app, "company_name", old_company_name, new_company_name)

        if "company_address" in data_changes:
            old_company_address = app.company_address
            new_company_address = data_changes["company_address"]
            app.update_safely(company_address=new_company_address)
            _create_history_application(
                app, "company_address", old_company_address, new_company_address
            )

        if "company_phone_number" in data_changes:
            old_company_phone_number = app.company_phone_number
            new_company_phone_number = data_changes["company_phone_number"]
            app.update_safely(company_phone_number=new_company_phone_number)
            _create_history_application(
                app, "company_phone_number", old_company_phone_number, new_company_phone_number
            )

        if "name_in_bank" in data_changes:
            old_name_in_bank = app.name_in_bank
            new_name_in_bank = data_changes["name_in_bank"]
            app.update_safely(name_in_bank=new_name_in_bank)
            _create_history_application(app, "name_in_bank", old_name_in_bank, new_name_in_bank)

        # change address of application
        if "address_street_num" in data_changes:
            old_address_street_num = app.address_street_num
            new_address_street_num = data_changes["address_street_num"]
            app.update_safely(address_street_num=new_address_street_num)
            _create_history_application(
                app, "address_street_num", old_address_street_num, new_address_street_num
            )

        if "address_provinsi" in data_changes:
            old_address_provinsi = app.address_provinsi
            new_address_provinsi = data_changes["address_provinsi"]
            app.update_safely(address_provinsi=new_address_provinsi)
            _create_history_application(
                app, "address_provinsi", old_address_provinsi, new_address_provinsi
            )

        if "address_kabupaten" in data_changes:
            old_address_kabupaten = app.address_kabupaten
            new_address_kabupaten = data_changes["address_kabupaten"]
            app.update_safely(address_kabupaten=new_address_kabupaten)
            _create_history_application(
                app, "address_kabupaten", old_address_kabupaten, new_address_kabupaten
            )

        if "address_kecamatan" in data_changes:
            old_address_kecamatan = app.address_kecamatan
            new_address_kecamatan = data_changes["address_kecamatan"]
            app.update_safely(address_kecamatan=new_address_kecamatan)
            _create_history_application(
                app, "address_kecamatan", old_address_kecamatan, new_address_kecamatan
            )

        if "address_kelurahan" in data_changes:
            old_address_kelurahan = app.address_kelurahan
            new_address_kelurahan = data_changes["address_kelurahan"]
            app.update_safely(address_kelurahan=new_address_kelurahan)
            _create_history_application(
                app, "address_kelurahan", old_address_kelurahan, new_address_kelurahan
            )

        if "address_kodepos" in data_changes:
            old_address_kodepos = app.address_kodepos
            new_address_kodepos = data_changes["address_kodepos"]
            app.update_safely(address_kodepos=new_address_kodepos)
            _create_history_application(
                app, "address_kodepos", old_address_kodepos, new_address_kodepos
            )

        if "occupied_since" in data_changes:
            old_occupied_since = app.occupied_since
            new_occupied_since = data_changes["occupied_since"]
            app.update_safely(occupied_since=new_occupied_since)
            _create_history_application(
                app, "occupied_since", old_occupied_since, new_occupied_since
            )

        if "home_status" in data_changes:
            old_home_status = app.home_status
            new_home_status = data_changes["home_status"]
            app.update_safely(home_status=new_home_status)
            _create_history_application(app, "home_status", old_home_status, new_home_status)

        if "job_industry" in data_changes:
            old_job_industry = app.job_industry
            new_job_industry = data_changes["job_industry"]
            app.update_safely(job_industry=new_job_industry)
            _create_history_application(app, "job_industry", old_job_industry, new_job_industry)

        if "job_type" in data_changes:
            old_job_type = app.job_type
            new_job_type = data_changes["job_type"]
            app.update_safely(job_type=new_job_type)
            _create_history_application(app, "job_type", old_job_type, new_job_type)

        if "job_description" in data_changes:
            old_job_description = app.job_description
            new_job_description = data_changes["job_description"]
            app.update_safely(job_description=new_job_description)
            _create_history_application(
                app, "job_description", old_job_description, new_job_description
            )

        if "monthly_income" in data_changes:
            old_monthly_income = app.monthly_income
            new_monthly_income = data_changes["monthly_income"]
            app.update_safely(monthly_income=new_monthly_income)
            _create_history_application(
                app, "monthly_income", old_monthly_income, new_monthly_income
            )

        if "monthly_expenses" in data_changes:
            old_monthly_expenses = app.monthly_expenses
            new_monthly_expenses = data_changes["monthly_expenses"]
            app.update_safely(monthly_expenses=new_monthly_expenses)
            _create_history_application(
                app, "monthly_expenses", old_monthly_expenses, new_monthly_expenses
            )

        if "mother_maiden_name" in data_changes:
            old_mother_maiden_name = app.customer.mother_maiden_name
            new_mother_maiden_name = data_changes["mother_maiden_name"]
            app.customer.update_safely(mother_maiden_name=new_mother_maiden_name)
            _create_history_customer(
                app.customer, "mother_maiden_name", old_mother_maiden_name, new_mother_maiden_name
            )

        if "fullname" in data_changes:
            # change fullname for all application
            new_fullname = data_changes["fullname"]
            for temp_app in app.customer.application_set.all():
                old_fullname = temp_app.fullname
                new_fullname = data_changes["fullname"]
                temp_app.update_safely(fullname=new_fullname)
                _create_history_application(temp_app, "fullname", old_fullname, new_fullname)

            cust = app.customer
            old_fullname = cust.fullname
            cust.update_safely(fullname=new_fullname)
            _create_history_customer(cust, "fullname", old_fullname, new_fullname)

        if "mobile_phone_1" in data_changes:
            if prevent_duplicate:
                data_with_current_mobile_phone_1 = (
                    Application.objects.filter(mobile_phone_1=data_changes["mobile_phone_1"])
                    .exclude(customer_id=app.customer_id)
                    .values_list('pk', flat=True)
                )
                data_with_current_mobile_phone_1 = list(data_with_current_mobile_phone_1)
                if len(data_with_current_mobile_phone_1) != 0:
                    raise Exception(
                        "mobile_phone_1 already exist in " + str(data_with_current_mobile_phone_1)
                    )
                data_with_current_phone = (
                    Customer.objects.filter(phone=data_changes["mobile_phone_1"])
                    .exclude(pk=app.customer_id)
                    .values_list('pk', flat=True)
                )
                data_with_current_phone = list(data_with_current_phone)
                if len(data_with_current_phone) != 0:
                    raise Exception("phone already exists (" + str(data_with_current_phone))

                _check_duplicate_username(app.customer_id, data_changes["mobile_phone_1"])

            # change mobile_phone_1 for all application
            new_mobile_phone_1 = data_changes["mobile_phone_1"]
            for temp_app in app.customer.application_set.all():
                old_mobile_phone_1 = temp_app.mobile_phone_1
                # check for 190 Grab application
                if temp_app.is_grab() and temp_app.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
                    raise Exception(f"Application {temp_app.id} exists in 190 status (Grab active)")
                elif temp_app.is_grab() and temp_app.application_status_id not in grab_graveyard_statuses:
                    raise Exception(f"Application {temp_app.id} exists in {temp_app.application_status_id} (Not Graveyard Status)")
                temp_app.update_safely(mobile_phone_1=new_mobile_phone_1)
                _create_history_application(
                    temp_app, "mobile_phone_1", old_mobile_phone_1, new_mobile_phone_1
                )

            cust = app.customer
            old_phone = cust.phone
            cust.update_safely(phone=new_mobile_phone_1)

            # check for grab application
            if app.is_grab():
                # create application note for Grab app
                ApplicationNote.objects.create(
                    note_text="Change mobile_phone_1 for Grab app",
                    application_id=app_id,
                    application_history_id=None,
                )
                # check Grab Customer Data
                grab_cust = GrabCustomerData.objects.get_or_none(customer=cust)
                if grab_cust:
                    # for Grab application only for wrong app, for correct Grab app please change via CRM (switch process)
                    grab_cust.grab_validation_status = False
                    grab_cust.otp_status = "UNVERIFIED"
                    grab_cust.hashed_phone_number = ""
                    grab_cust.phone_number = ""
                    grab_cust.save(update_fields=["grab_validation_status", "otp_status", "hashed_phone_number", "phone_number"])
            _create_history_customer(cust, "phone", old_phone, new_mobile_phone_1)

            _change_username(cust.id, new_mobile_phone_1, 'mobile_phone_1')

        if "kin_mobile_phone" in data_changes:
            new_kin_mobile_phone = data_changes["kin_mobile_phone"]
            old_kin_mobile_phone = app.kin_mobile_phone
            app.update_safely(kin_mobile_phone=new_kin_mobile_phone)
            _create_history_application(
                app, "kin_mobile_phone", old_kin_mobile_phone, new_kin_mobile_phone
            )

        if "kin_name" in data_changes:
            new_kin_name = data_changes["kin_name"]
            old_kin_name = app.kin_name
            app.update_safely(kin_name=new_kin_name)
            _create_history_application(app, "kin_name", old_kin_name, new_kin_name)

        if "kin_relationship" in data_changes:
            new_kin_relationship = data_changes["kin_relationship"]
            old_kin_relationship = app.kin_relationship
            app.update_safely(kin_relationship=new_kin_relationship)
            _create_history_application(
                app, "kin_relationship", old_kin_relationship, new_kin_relationship
            )

        if "close_kin_mobile_phone" in data_changes:
            new_close_kin_mobile_phone = data_changes["close_kin_mobile_phone"]
            old_close_kin_mobile_phone = app.close_kin_mobile_phone
            app.update_safely(close_kin_mobile_phone=new_close_kin_mobile_phone)
            _create_history_application(
                app,
                "close_kin_mobile_phone",
                old_close_kin_mobile_phone,
                new_close_kin_mobile_phone,
            )

        if "close_kin_name" in data_changes:
            new_close_kin_name = data_changes["close_kin_name"]
            old_close_kin_name = app.close_kin_name
            app.update_safely(close_kin_name=new_close_kin_name)
            _create_history_application(
                app, "close_kin_name", old_close_kin_name, new_close_kin_name
            )

        if "close_kin_relationship" in data_changes:
            new_close_kin_relationship = data_changes["close_kin_relationship"]
            old_close_kin_relationship = app.close_kin_relationship
            app.update_safely(close_kin_relationship=new_close_kin_relationship)
            _create_history_application(
                app,
                "close_kin_relationship",
                old_close_kin_relationship,
                new_close_kin_relationship,
            )

        if "spouse_mobile_phone" in data_changes:
            new_spouse_mobile_phone = data_changes["spouse_mobile_phone"]
            old_spouse_mobile_phone = app.spouse_mobile_phone
            app.update_safely(spouse_mobile_phone=new_spouse_mobile_phone)
            _create_history_application(
                app, "spouse_mobile_phone", old_spouse_mobile_phone, new_spouse_mobile_phone
            )

        if "spouse_name" in data_changes:
            new_spouse_name = data_changes["spouse_name"]
            old_spouse_name = app.spouse_name
            app.update_safely(spouse_name=new_spouse_name)
            _create_history_application(app, "spouse_name", old_spouse_name, new_spouse_name)

        if "email" in data_changes:
            if prevent_duplicate:
                if data_changes["email"] != "" and data_changes["email"] is not None:
                    data_with_current_email = Application.objects.filter(
                        email=data_changes["email"]
                    )
                    if len(data_with_current_email) != 0:
                        for temp_app in data_with_current_email:
                            if temp_app.customer.id != app.customer.id:
                                raise Exception("email already exist in " + str(temp_app.id))

                _check_duplicate_username(app.customer_id, data_changes["email"])

            # change email for all application
            new_email = data_changes["email"]
            email_pii_data = {}
            for temp_app in app.customer.application_set.all():
                old_email = temp_app.email
                temp_app.update_safely(email=new_email)
                _create_history_application(temp_app, "email", old_email, new_email)

            cust = app.customer
            old_email = cust.email
            cust.update_safely(email=new_email)
            _create_history_customer(cust, "email", old_email, new_email)
            auth_user_id = cust.user_id
            auth_user = User.objects.get(pk=auth_user_id)
            old_email = auth_user.email
            auth_user.email = new_email
            auth_user.save(update_fields=['email'])
            _create_history_auth_user(auth_user, app.customer, "email", old_email, new_email)

            _change_username(cust.id, new_email, 'email')
            email_pii_data[PiiSource.AUTH_USER] = [
                {'resource': cust.user, 'resource_id': cust.user.id, 'fields': ['email']}
            ]
            if is_allow_to_token_pii_data:
                with transaction.atomic(using='logging_db'):
                    email_pii_data = prepare_pii_event(email_pii_data)
                    if email_pii_data:
                        execute_after_transaction_safely(lambda: tokenize_pii_data(email_pii_data))

            if app.is_grab():
                # create application note for Grab app
                ApplicationNote.objects.create(
                    note_text="Change email for Grab app",
                    application_id=app_id,
                    application_history_id=None,
                )

        if "status" in data_changes:
            if "value" in data_changes["status"] and "reason" in data_changes["status"]:
                res = process_application_status_change(
                    app_id, data_changes["status"]["value"], data_changes["status"]["reason"]
                )
                if res is False:
                    raise Exception("cannot move status")

        if "cdate" in data_changes:
            old_cdate = app.cdate
            new_cdate = data_changes["cdate"]
            app.update_safely(cdate=new_cdate)
            _create_history_application(app, "cdate", old_cdate, new_cdate)

        if "can_reapply" in data_changes:
            cust = app.customer
            old_can_reapply = cust.can_reapply
            new_can_reapply = data_changes["can_reapply"] == 'True'
            cust.can_reapply = new_can_reapply
            cust.save(update_fields=['can_reapply'])
            _create_history_customer(cust, "can_reapply", old_can_reapply, new_can_reapply)

        if "can_reapply_date" in data_changes:
            cust = app.customer
            old_can_reapply_date = str(cust.can_reapply_date)

            try:
                additional_month = int(data_changes["can_reapply_date"])
            except Exception:
                # if data_changes['can_reapply_date'] == "", then we assume it's change to None
                additional_month = -1

            expired_date = None

            # allowed additional_month : -1, 0, 1, 2, ...
            eligible_to_change = False
            if additional_month >= 0:  # additional month
                today = timezone.localtime(timezone.now())
                expired_date = today + relativedelta(months=+additional_month)
                eligible_to_change = True
            elif additional_month == -1:
                expired_date = None
                eligible_to_change = True

            if eligible_to_change:
                cust.can_reapply_date = expired_date
                cust.save(update_fields=['can_reapply_date'])
                _create_history_customer(
                    cust,
                    "can_reapply_date",
                    old_can_reapply_date,
                    str(expired_date),
                )

        if "nik" in data_changes:
            # validate
            data_with_current_nik = Customer.objects.filter(nik=data_changes["nik"])
            if len(data_with_current_nik) != 0:
                for temp_cust in data_with_current_nik:
                    if temp_cust.id != app.customer.id:
                        raise Exception("nik already exists")
            data_with_current_ktp = Application.objects.filter(ktp=data_changes["nik"])
            if len(data_with_current_ktp) != 0:
                for temp_app in data_with_current_ktp:
                    if temp_app.customer_id != app.customer_id:
                        raise Exception("ktp already exists")
            data_with_current_username = User.objects.filter(username=data_changes["nik"])
            if len(data_with_current_username) != 0:
                for temp_user in data_with_current_username:
                    temp_custs = Customer.objects.filter(user_id=temp_user.id)
                    for temp_cust in temp_custs:
                        if temp_cust.id != app.customer_id:
                            raise Exception("username already exists")

            # change the data
            old_nik = app.customer.nik
            new_nik = data_changes["nik"]
            app.customer.update_safely(nik=new_nik)
            _create_history_customer(app.customer, "nik", old_nik, new_nik)

            old_ktp = app.ktp
            new_ktp = data_changes["nik"]
            app.update_safely(ktp=new_ktp)
            _create_history_application(app, "ktp", old_ktp, new_ktp)

            auth_user_id = app.customer.user_id
            auth_user = User.objects.get(pk=auth_user_id)
            old_username = auth_user.username
            if old_username == old_nik:
                auth_user.username = data_changes["nik"]
                auth_user.save(update_fields=['username'])
                _create_history_auth_user(
                    auth_user, app.customer, "username", old_username, data_changes["nik"]
                )
            if app.is_grab():
                # create application note for Grab app
                ApplicationNote.objects.create(
                    note_text="Change nik for Grab app",
                    application_id=app_id,
                    application_history_id=None,
                )

        if "credit_score" in data_changes:
            credit_score = app.creditscore
            old_score = credit_score.score
            credit_score.update_safely(score=data_changes["credit_score"])
            ApplicationNote.objects.create(
                note_text="change score pgood from "
                + str(old_score)
                + " to "
                + str(data_changes["credit_score"]),
                application_id=app_id,
                application_history_id=None,
            )
            _create_history_application(
                app, "credit_score", old_score, data_changes["credit_score"]
            )

        if "name_bank_validation_status" in data_changes:
            nbv_id = app.name_bank_validation_id
            nbv = NameBankValidation.objects.get(pk=nbv_id)
            if nbv is not None:
                nbv.validation_status = 'SUCCESS'
                nbv.save(update_fields=['validation_status'])
                nbv.create_history('create', ['validation_status'])

        if "name_bank_validation_account_number" in data_changes:
            nbv_id = app.name_bank_validation_id
            nbv = NameBankValidation.objects.get(pk=nbv_id)
            if nbv is not None:
                nbv.account_number = data_changes['name_bank_validation_account_number']
                nbv.save(update_fields=['account_number'])
                nbv.create_history('update', ['account_number'])

        if "upsert_skiptrace" in data_changes:
            if (
                "phone" in data_changes["upsert_skiptrace"]
                and "source" in data_changes["upsert_skiptrace"]
            ):

                # try update first
                updated = False
                skiptraces = Skiptrace.objects.filter(customer_id=app.customer.id)
                for skiptrace in skiptraces:
                    if skiptrace.contact_source == data_changes["upsert_skiptrace"]["source"]:
                        skiptrace.phone_number = format_e164_indo_phone_number(
                            data_changes["upsert_skiptrace"]["phone"]
                        )
                        skiptrace.save(update_fields=['phone_number'])
                        updated = True
                        break

                if not updated:
                    Skiptrace.objects.create(
                        contact_source=data_changes["upsert_skiptrace"]["source"],
                        phone_number=format_e164_indo_phone_number(
                            data_changes["upsert_skiptrace"]["phone"]
                        ),
                        customer_id=app.customer.id,
                        application=app,
                        contact_name=app.fullname,
                    )

        if "insert_skiptrace" in data_changes:
            if (
                "phone" in data_changes["insert_skiptrace"]
                and "source" in data_changes["insert_skiptrace"]
            ):

                Skiptrace.objects.create(
                    contact_source=data_changes["insert_skiptrace"]["source"],
                    phone_number=format_e164_indo_phone_number(
                        data_changes["insert_skiptrace"]["phone"]
                    ),
                    customer_id=app.customer.id,
                    application=app,
                    contact_name=app.fullname,
                )

        if application_note is not None:
            ApplicationNote.objects.create(
                note_text=application_note, application_id=app_id, application_history_id=None
            )
        logger.info(
            {
                'action': 'change application data',
                'id': app_id,
                'type_of_id': "Application",
                'requsted_data_change': data_changes,
            }
        )


def _create_history_application(app, field, old_value, new_value):
    application_field_change = ApplicationFieldChange.objects.create(
        application=app,
        field_name=field,
        old_value=old_value,
        new_value=new_value,
    )

    return application_field_change


def _create_history_auth_user(auth_user, customer, field, old_value, new_value):
    auth_user_field_change = AuthUserFieldChange.objects.create(
        user=auth_user,
        field_name=field,
        old_value=old_value,
        new_value=new_value,
        customer=customer,
    )

    return auth_user_field_change


def _create_history_customer(cust, field, old_value, new_value):
    customer_field_change = CustomerFieldChange.objects.create(
        customer=cust,
        field_name=field,
        old_value=old_value,
        new_value=new_value,
    )

    return customer_field_change


def conditional_change_application_data(
    data, application_note=None, prevent_duplicate=True, actor_id=None, need_track=True
):

    result = {}
    duplicate_data = 0

    for application_change in data:
        app_id = application_change["app_id"]
        data_changes = application_change["data_changes"]
        status_required = (
            application_change["status_required"]
            if "status_required" in application_change
            else None
        )
        should_last_application = (
            application_change["should_last_application"]
            if "should_last_application" in application_change
            else False
        )
        key = _create_key([app_id, data_changes])
        if key not in result:
            result[key] = []
        if len(result[key]) > 0:
            duplicate_data += 1
            continue
        result[key].append("processed")
        # -- fix --
        if need_track:
            track_agent_retrofix(
                'conditional_change_application_data', app_id, data_changes, actor_id
            )
        app = Application.objects.get(pk=app_id)
        if status_required and app.status != status_required:
            result[key].append(
                "cannot change application data, because the status is " + str(app.status)
            )
            continue
        if should_last_application:
            last_app = Application.objects.filter(customer_id=app.customer_id).last()
            if last_app.id != app.id:
                result[key].append(
                    "cannot change application data, because it's not last application"
                )
                continue

        _change_application_data(app_id, data_changes, application_note, prevent_duplicate)
        # ---------
        result[key].append("success")
    resp = {
        "summary": _get_summary_from_result(result),
        "duplicate_data": duplicate_data,
        "result": result,
    }
    return resp
