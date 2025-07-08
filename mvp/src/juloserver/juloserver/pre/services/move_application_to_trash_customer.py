from django.db import transaction
from juloserver.julo.models import Application, ApplicationFieldChange, Loan, Customer
from juloserver.julolog.julolog import JuloLog
from juloserver.pre.services.onboarding.change_force import change_force

logger = JuloLog(__name__)


def _create_history_application(app, field, old_value, new_value):
    with transaction.atomic():
        ApplicationFieldChange.objects.create(
            application=app,
            field_name=field,
            old_value=old_value,
            new_value=new_value,
        )


def move_application_to_trash_customer(app_id):
    with transaction.atomic():
        try:
            _do_change_customer_id(app_id)
        except Exception as e:
            logger.info(
                {
                    "function": "move_application_to_trash_customer",
                    "app_id": app_id,
                    "error": str(e),
                }
            )
    return


def _do_change_customer_id(
    app_id, ignore_loan=False, email_of_trash_app='samuel.ricky_trash_account@julofinance.com'
):
    app = Application.objects.get(pk=app_id)
    loans = Loan.objects.filter(application_id2=app.id).exists()
    if loans and not ignore_loan:
        raise Exception("this application already have loan")

    cust_trash = Customer.objects.filter(email=email_of_trash_app).last()
    old_customer_id = app.customer_id
    app.customer_id = cust_trash.id
    app.save()
    _create_history_application(app, "customer_id", old_customer_id, cust_trash.id)
    if app.status == 137:
        # move to x106 if the status is x100
        change_force(app_id, {"status": {"value": 106, "reason": "Moved to trash customer"}}, 1)

    _clear_data(app_id)


def _clear_data(app_id):
    app = Application.objects.get(pk=app_id)
    # replace NIK with 444 444
    # make phone number and email is null
    ktp = app.ktp
    new_nik = "444444" + app.ktp[6:]
    old_mobile_phone_1 = app.mobile_phone_1
    old_email = app.email
    old_bank_account_number = app.bank_account_number
    old_mobile_phone_2 = app.mobile_phone_2
    old_landlord_mobile_phone = app.landlord_mobile_phone
    old_kin_mobile_phone = app.kin_mobile_phone
    old_close_kin_mobile_phone = app.close_kin_mobile_phone
    old_spouse_mobile_phone = app.spouse_mobile_phone
    old_company_phone_number = app.company_phone_number

    app.update_safely(
        ktp=new_nik,
        mobile_phone_1=None,
        email=None,
        bank_account_number=None,
        mobile_phone_2=None,
        landlord_mobile_phone=None,
        kin_mobile_phone=None,
        close_kin_mobile_phone=None,
        spouse_mobile_phone=None,
        company_phone_number=None,
    )
    _create_history_application(app, "ktp", ktp, new_nik)
    _create_history_application(app, "mobile_phone_1", old_mobile_phone_1, None)
    _create_history_application(app, "email", old_email, None)
    _create_history_application(app, "bank_account_number", old_bank_account_number, None)
    _create_history_application(app, "mobile_phone_2", old_mobile_phone_2, None)
    _create_history_application(app, "landlord_mobile_phone", old_landlord_mobile_phone, None)
    _create_history_application(app, "kin_mobile_phone", old_kin_mobile_phone, None)
    _create_history_application(app, "close_kin_mobile_phone", old_close_kin_mobile_phone, None)
    _create_history_application(app, "spouse_mobile_phone", old_spouse_mobile_phone, None)
    _create_history_application(app, "company_phone_number", old_company_phone_number, None)

    if app.account_id is not None:
        old_account_id = app.account_id
        app.update_safely(account_id=None)
        _create_history_application(app, "account_id", old_account_id, None)
