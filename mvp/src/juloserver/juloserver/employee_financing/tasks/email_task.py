"""
All task related to employee financing email
"""
import json
import logging
from datetime import timedelta, date

from babel.dates import format_date
from celery import task
from dateutil.relativedelta import relativedelta
from datetime import datetime
from django.conf import settings
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from juloserver.account.models import CreditLimitGeneration
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.models import (Application, ApplicationNote, EmailHistory,
                                    PaymentMethod, ReminderEmailSetting, StatusLookup)
from juloserver.julo.services import (get_pdf_content_from_html)
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.constants import (EmailReminderModuleType,
                                       EmailReminderType)
from juloserver.julo.utils import display_rupiah
from juloserver.employee_financing.models import (
    Company, EmFinancingWFAccessToken, EmployeeFinancingFormURLEmailContent
)
from juloserver.employee_financing.utils import (
    create_or_update_token,
    encode_jwt_token
)
from juloserver.partnership.clients import get_partnership_email_client
from juloserver.partnership.constants import EFWebFormType


# Disbursement Import
from django.template import (
    Template,
    Context,
)

from juloserver.julo.models import (
    Loan,
    FeatureSetting
)
from babel.dates import format_date
from juloserver.julo.constants import (
    FeatureNameConst
)

# Disbursement Import
from django.template import (
    Template,
    Context,
)

from juloserver.julo.models import (
    Loan,
    FeatureSetting
)
from babel.dates import format_date
from juloserver.julo.constants import (
    FeatureNameConst
)
from juloserver.julocore.python2.utils import py2round

logger = logging.getLogger(__name__)


def trigger_send_email_repayment_reminder(company_data, email_repayment_setting):
    email_histories = []
    company_name = company_data.get("company_name")
    company_email = company_data.get("company_email")
    company_recipients = company_data.get("company_recipients")

    logger.info({
        "action": "send_repayment_email_reminder",
        "company_name": company_name,
        "company_email": company_email,
        "company_recipients": company_recipients,
        "due_date": company_data.get("due_date"),
        "due_amount": display_rupiah(company_data.get("total_due_amount")),
    })

    content_param = {
        'company_name': company_name,
        'company_email': company_email,
        'due_date': company_data.get("due_date"),
        'due_amount': display_rupiah(company_data.get("total_due_amount"))
    }
    content_formatted = email_repayment_setting.content.format(**content_param)

    logger.info(f"content_formatted: {content_formatted}")

    html_content = render_to_string(
        template_name='email_template_pilot_ef_repayment_reminder.html',
        context={'content': content_formatted},
    )

    email_from = "ops.employee_financing@julo.co.id"
    if email_repayment_setting.sender:
        email_from = email_repayment_setting.sender
    email_to = company_recipients if company_recipients else company_email
    email_cc = email_repayment_setting.recipients
    subject = "{} - Tagihan yang akan jatuh tempo".format(
        company_email)

    julo_email_client = get_julo_email_client()
    julo_email_client.send_email(
        subject, html_content, email_to, email_from=email_from,
        email_cc=email_cc, content_type="text/html"
    )

    email_history = EmailHistory(
        customer_id=company_data.get("customer_id"),
        to_email=email_to,
        subject=subject,
        message_content=html_content,
        template_code='employee_financing_repayment_reminder_email',
        cc_email=email_cc
    )
    email_histories.append(email_history)
    return email_histories


@task(name="send_email_at_190_for_pilot_ef_csv_upload",
      queue="employee_financing_email_at_190_queue")
def send_email_at_190_for_pilot_ef_csv_upload(application_id):
    application = Application.objects.select_related('company').get(id=application_id)
    app_note = ApplicationNote.objects.filter(application_id=application.id).last()
    app_note_dict = json.loads(app_note.note_text)
    company = application.company

    # construct context
    company_name = company.name
    approved_limit = int(app_note_dict.get("approved_limit"))
    interest = f'{app_note_dict.get("interest")}%'
    provision_fee = f'{app_note_dict.get("provision_fee")}%'
    max_tenor = int(app_note_dict.get("max_tenor"))
    x190_history = application.applicationhistory_set.get(status_new=190)
    context = {
        'fullname': application.fullname_with_title,
        'account_set_limit': display_rupiah(approved_limit),
        'cdate_190': x190_history.cdate,
        'company_name': company_name,
        'provision_fee': provision_fee,
        'interest': interest,
        'max_tenor': max_tenor
    }

    email_template = render_to_string('email_template_pilot_ef.html', context=context)
    email_from = "ops.employee_financing@julo.co.id"
    email_to = application.email
    subject = "{} - Pengajuan Kredit Limit JULO telah disetujui, balas YA untuk melanjutkan".format(
        application.email)

    def get_sphp_attachment():
        attachment_name = "%s-%s.pdf" % (application.fullname, application.application_xid)
        attachment_string = get_sphp_template(application)
        pdf_content = get_pdf_content_from_html(attachment_string, attachment_name)
        attachment_dict = {
            "content": pdf_content,
            "filename": attachment_name,
            "type": "application/pdf"
        }
        return attachment_dict, "text/html"

    attachment_dict, content_type = get_sphp_attachment()
    julo_email_client = get_julo_email_client()

    msg = email_template
    julo_email_client.send_email(
        subject, msg, email_to, email_from=email_from,
        attachment_dict=attachment_dict, content_type=content_type)
    EmailHistory.objects.create(
        customer_id=application.customer_id,
        application_id=application.id,
        to_email=email_to,
        subject=subject,
        message_content=msg,
        template_code='employee_financing_190_email'
    )


@task(name="send_email_at_rejected_for_pilot_ef_csv_upload", queue="employee_financing_global_queue")
def send_email_at_rejected_for_pilot_ef_csv_upload(fullname, email):
    context = {
        'fullname': fullname,
    }

    email_template = render_to_string('email_template_pilot_ef_rejected.html', context=context)
    email_from = "ops.employee_financing@julo.co.id"
    email_to = email
    subject = "{} - Maaf pengajuan pinjaman JULO anda belum disetujui".format(
        email)

    julo_email_client = get_julo_email_client()

    msg = email_template
    julo_email_client.send_email(
        subject, msg, email_to, email_from=email_from, content_type="text/html")
    EmailHistory.objects.create(
        to_email=email_to,
        subject=subject,
        message_content=msg,
        template_code='employee_financing_rejected_email'
    )


def get_sphp_template(application):
    credit_limit = CreditLimitGeneration.objects.get(application=application)

    payment_method = PaymentMethod.objects.get(
        is_primary=True,
        customer_id=application.customer_id)

    bank_name = payment_method.payment_method_name
    bank_code = payment_method.bank_code if 'BCA' not in bank_name else None

    sphp_date = timezone.now().date()
    context = {
        'application': application,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'full_address': application.full_address,
        'julo_bank_code': bank_code,
        'julo_bank_name': bank_name,
        'julo_bank_account_number': payment_method.virtual_account,
        'date_today': format_date(sphp_date, 'd MMMM yyyy', locale='id_ID'),
        'background_image': settings.SPHP_STATIC_FILE_PATH + 'julo-a-4@3x.png',
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'account_set_limit': display_rupiah(credit_limit.set_limit)
    }
    sphp_template = render_to_string('sphp_pilot_partner_upload_template.html', context=context)

    return sphp_template


@task(name='email_notification_for_employee_financing_loan',
      queue='employee_financing_email_disbursement_queue')
def email_notification_for_employee_financing_loan(loan_id):
    from ..services import get_employee_financing_sphp_content

    loan = Loan.objects.filter(id=loan_id).select_related('account').first()
    application = loan.account.last_application

    context = {
        'fullname': application.fullname_with_title,
        'loan_amount': display_rupiah(loan.loan_amount),
        'loan_disbursed_amount': display_rupiah(loan.loan_disbursement_amount),
        'due_date': format_date(
            loan.payment_set.order_by('id').first().due_date, 'dd-MM-yyyy', locale='id_ID'),
    }

    context = Context(context)
    email_template = render_to_string('email_pilot_partner_success_disburse.html',
                                      context=context)
    template = Template(email_template)
    email_from = "ops.employee_financing@julo.co.id"
    email_to = application.email
    subject = "Pinjaman JULO telah aktif dan dana telah dicairkan"

    attachment_name = "%s-%s.pdf" % (application.fullname, application.application_xid)
    attachment_string = get_employee_financing_sphp_content(loan)
    pdf_content = get_pdf_content_from_html(attachment_string, attachment_name)
    attachment_dict = {
        "content": pdf_content,
        "filename": attachment_name,
        "type": "application/pdf"
    }
    julo_email_client = get_julo_email_client()
    msg = str(template.render(context))
    status, _, headers = julo_email_client.send_email(
        subject, msg, email_to, email_from=email_from,
        attachment_dict=attachment_dict, content_type='text/html')
    EmailHistory.objects.create(
        customer_id=application.customer_id,
        application_id=application.id,
        payment_id=loan.payment_set.first().id,
        to_email=email_to,
        subject=subject,
        message_content=msg,
        template_code='employee_financing_220_email',
        sg_message_id=headers['X-Message-Id'],
    )


@task(name="send_repayment_email_reminder", queue="employee_financing_global_queue")
def send_repayment_email_reminder():
    email_repayment_setting = ReminderEmailSetting.objects.filter(
        module_type=EmailReminderModuleType.EMPLOYEE_FINANCING,
        email_type=EmailReminderType.REPAYMENT,
        enabled=True
    ).first()

    if not email_repayment_setting:
        logger.error({
            "action": "send_repayment_email_reminder",
            "error": "email repayment setting not found or not active"
        })
        return

    today = timezone.localtime(timezone.now()).date()
    company_ids = Company.objects.values('id')

    payment_paid_statuses = [
        StatusLookup.PAID_ON_TIME_CODE,
        StatusLookup.PAID_WITHIN_GRACE_PERIOD_CODE,
        StatusLookup.PAID_LATE_CODE
    ]
    account_payment_dict = dict()
    account_payments = AccountPayment.objects.exclude(
        due_amount=0
    ).filter(
        ~Q(status__in=payment_paid_statuses),
        account_id__isnull=False,
        due_date__month=today.month,
        account__application__company_id__isnull=False,
    ).values(
        'account__application__company_id',
        'account__application__company__name',
        'account__application__company__email',
        'account__application__company__recipients',
        'account__application',
        'account__customer_id',
        'account_id',
        'due_date',
        'due_amount'
    )

    for account in account_payments.iterator():
        company_id = account.get("account__application__company_id")
        due_amount = account.get("due_amount")
        if account_payment_dict.get(company_id):
            account_payment_dict[company_id]["total_due_amount"] += due_amount
        else:
            acc_dict = {
                company_id: {
                    "company_name": account.get("account__application__company__name"),
                    "company_email": account.get("account__application__company__email"),
                    "company_recipients": account.get("account__application__company__recipients"),
                    "application_id": account.get("account__application"),
                    "customer_id": account.get("account__customer_id"),
                    "due_date": account.get("due_date"),
                    "total_due_amount": due_amount
                }
            }
            account_payment_dict.update(acc_dict)

    email_histories = []
    for company_id in company_ids.iterator():
        company_data = account_payment_dict.get(company_id.get("id"))

        # check if today is same date as account payment due date minus email_repayment_setting.days_before
        for day in email_repayment_setting.days_before:
            if company_data and today == company_data.get("due_date") - timedelta(days=day):
                triggered_before_data = trigger_send_email_repayment_reminder(company_data, email_repayment_setting)
                email_histories.extend(triggered_before_data)

        # check if today is same date as account payment due date plus email_repayment_setting.days_after
        for day in email_repayment_setting.days_after:
            if company_data and today == company_data.get("due_date") + timedelta(days=day):
                triggered_after_data = trigger_send_email_repayment_reminder(company_data, email_repayment_setting)
                email_histories.extend(triggered_after_data)

    EmailHistory.objects.bulk_create(email_histories, batch_size=25)


@task(name="run_send_repayment_email_reminder", queue="employee_financing_global_queue")
def run_send_repayment_email_reminder():
    """
    check and run send repayment email reminder task,
    later on will read the schedule when the task called from ReminderEmailSetting obj
    the goal is to create a dynamic periodic task by user input
    """
    email_repayment_setting = ReminderEmailSetting.objects.filter(
        module_type=EmailReminderModuleType.EMPLOYEE_FINANCING,
        email_type=EmailReminderType.REPAYMENT,
        enabled=True
    ).first()

    if not email_repayment_setting:
        logger.error({
            "action": "run_send_repayment_email_reminder",
            "error": "email repayment setting not found or not active"
        })
        return
    now = timezone.localtime(timezone.now())
    hour = email_repayment_setting.time_scheduled.hour
    minute = email_repayment_setting.time_scheduled.minute
    later = timezone.localtime(timezone.now()).replace(
        hour=hour, minute=minute, second=0, microsecond=0)
    countdown = int(py2round((later - now).total_seconds()))
    # send base on schedule on reminder email setting
    if countdown >= 0:
        send_repayment_email_reminder.apply_async(countdown=countdown)
        logger.info({
            'action': 'send_repayment_email_reminder',
            'message': 'success run'
        })
    else:
        logger.info({
            'action': 'send_repayment_email_reminder',
            'message': 'run failed because time had passed'
        })


@task(name="send_email_to_valid_employees", queue="employee_financing_global_queue")
def send_email_to_valid_employees(data, email_content, email_subject, email_salutation):
    company = Company.objects.filter(id=data['company_id'], is_active=True).last()
    if not company:
        logger.error({
            "action": "send_email_to_valid_employees",
            "error": "company_id not exists"
        })
        return

    expired_at = timezone.localtime(timezone.now()).replace(hour=23, minute=59, second=59)
    user_access_tokens = create_or_update_token(
        data['email'], company, expired_at, EFWebFormType.APPLICATION, name=data['fullname']
    )
    context = {
        'fullname': data['fullname'],
        'email': data['email'],
        'token': user_access_tokens.token,
        'company_name': company.name,
        'limit_token_creation': user_access_tokens.limit_token_creation,
        'expired_at': expired_at
    }
    template_email_content = Template(email_content)
    context['email_content'] = template_email_content.render(Context(context))
    template_email_subject = Template(email_subject)
    template_email_salutation = Template(email_salutation)
    context['email_salutation'] = template_email_salutation.render(Context(context))
    email_template = render_to_string('email_template_valid_employee.html', context=context)
    email_from = "ops.employee_financing@julo.co.id"
    email_to = data['email']
    subject = template_email_subject.render(Context(context))
    julo_email_client = get_julo_email_client()
    msg = email_template
    julo_email_client.send_email(
        subject, msg, email_to, email_from=email_from, content_type="text/html")
    EmailHistory.objects.create(
        to_email=email_to,
        subject=subject,
        message_content=msg,
        template_code='employee_financing_valid_employee_email'
    )


@task(name="run_resend_email_web_form_application", queue="employee_financing_global_queue")
def run_resend_email_web_form_application() -> None:
    """
        This should be running on midnight
    """
    from juloserver.employee_financing.services import re_create_batch_user_tokens

    user_token_ids = re_create_batch_user_tokens(form_type=EFWebFormType.APPLICATION)
    if not user_token_ids:
        logger.info({
            "action": "run_resend_email_web_form_application",
            "time": timezone.localtime(timezone.now()),
            "message": "No token ids valid to re-send email"
        })
        return

    employee_financing_tokens = EmFinancingWFAccessToken.objects.filter(id__in=user_token_ids)\
        .order_by('id')
    for employee_financing_token in employee_financing_tokens.iterator():
        email = employee_financing_token.email
        name = employee_financing_token.name
        token = employee_financing_token.token
        expired_at = timezone.localtime(employee_financing_token.expired_at)

        limit = employee_financing_token.limit_token_creation
        send_email_web_form_application.delay(
            email=email, token=token, expired_at=expired_at, limit_submit_form=limit,
            name=name
        )


@task(name="run_resend_email_web_form_disbursement", queue="employee_financing_global_queue")
def run_resend_email_web_form_disbursement() -> None:
    """
        This should be running on midnight
    """
    from juloserver.employee_financing.services import re_create_batch_user_tokens

    user_token_ids = re_create_batch_user_tokens(form_type=EFWebFormType.DISBURSEMENT)
    if not user_token_ids:
        logger.info({
            "action": "run_resend_email_web_form_disbursement",
            "time": timezone.localtime(timezone.now()),
            "message": "No token ids valid to re-send email"
        })
        return

    employee_financing_tokens = EmFinancingWFAccessToken.objects.filter(id__in=user_token_ids)\
        .order_by('id')
    for employee_financing_token in employee_financing_tokens.iterator():
        email = employee_financing_token.email
        token = employee_financing_token.token
        expired_at = timezone.localtime(employee_financing_token.expired_at)

        limit = employee_financing_token.limit_token_creation
        send_email_web_form_disbursement.delay(
            email=email, token=token, expired_at=expired_at, limit_submit_form=limit
        )


@task(name="send_email_web_form_application", queue="employee_financing_global_queue")
def send_email_web_form_application(email: str, token: str, expired_at: date,
                                    limit_submit_form: int, name: str = None) -> None:

    email_content = EmployeeFinancingFormURLEmailContent.objects.filter(
        form_type=EFWebFormType.APPLICATION
    ).last()

    email_template_content = Template(email_content.email_content)

    base_julo_web_url = settings.JULO_WEB_URL
    if settings.ENVIRONMENT == 'staging':
        base_julo_web_url = "https://app-staging2.julo.co.id"

    email_content_context = Context(
        {
            'limit_token_creation': limit_submit_form,
            'expired_at': expired_at,
            'url': '{}/ef-pilot/{}?token={}'.format(
                base_julo_web_url, EFWebFormType.APPLICATION,
                token
            )
        }
    )
    context = {
        'fullname': name if name else "Bapak/Ibu",
        'content': email_template_content.render(email_content_context)
    }

    email_template = render_to_string('email_template_ef_send_form_url_to_email.html',
                                      context=context)
    email_from = "ops.employee_financing@julo.co.id"
    email_to = email
    subject = email_content.email_subject
    msg = email_template

    parntership_email_client = get_partnership_email_client()
    status, _, headers = parntership_email_client.send_email(
        subject=subject, content=msg, email_to=email_to, email_from=email_from,
        content_type="text/html"
    )
    EmailHistory.objects.create(
        status=str(status),
        to_email=email_to,
        subject=subject,
        message_content=msg,
        template_code='email_template_ef_send_form_url_to_email',
        sg_message_id=headers['X-Message-Id'],
    )


@task(name="send_email_web_form_disbursement", queue="employee_financing_global_queue")
def send_email_web_form_disbursement(email: str, token: str, expired_at: date,
                                     limit_submit_form: int) -> None:

    email_content = EmployeeFinancingFormURLEmailContent.objects.filter(
        form_type=EFWebFormType.DISBURSEMENT
    ).last()

    email_template_content = Template(email_content.email_content)
    base_julo_web_url = settings.JULO_WEB_URL
    if settings.ENVIRONMENT == 'staging':
        base_julo_web_url = "https://app-staging2.julo.co.id"

    email_content_context = Context(
        {
            'limit_token_creation': limit_submit_form,
            'expired_at': expired_at,
            'url': '{}/ef-pilot/{}?token={}'.format(
                base_julo_web_url, EFWebFormType.DISBURSEMENT,
                token
            )
        }
    )
    context = {
        'fullname': email,
        'content': email_template_content.render(email_content_context)
    }

    email_template = render_to_string('email_template_ef_send_form_url_to_email.html',
                                      context=context)
    email_from = "ops.employee_financing@julo.co.id"
    email_to = email
    subject = email_content.email_subject
    msg = email_template

    parntership_email_client = get_partnership_email_client()
    status, _, headers = parntership_email_client.send_email(
        subject=subject, content=msg, email_to=email_to, email_from=email_from,
        content_type="text/html"
    )
    EmailHistory.objects.create(
        status=str(status),
        to_email=email_to,
        subject=subject,
        message_content=msg,
        template_code='email_template_ef_send_form_url_to_email',
        sg_message_id=headers['X-Message-Id'],
    )


@task(name="send_email_sign_master_agreement_upload",
      queue="employee_financing_global_queue")
def send_email_sign_master_agreement_upload(application_id):
    application = Application.objects.select_related('company', 'customer').get(id=application_id)
    app_note = ApplicationNote.objects.filter(application_id=application.id).last()
    app_note_dict = json.loads(app_note.note_text)
    company = application.company
    customer = application.customer

    if not customer:
        raise ValueError('Customer not found with application_xid = {}'.format(application_id))

    # construct context 
    company_name = company.name
    approved_limit = int(app_note_dict.get("approved_limit"))
    interest = f'{app_note_dict.get("interest")}%'
    provision_fee = f'{app_note_dict.get("provision_fee")}%'
    max_tenor = int(app_note_dict.get("max_tenor"))
    x190_history = application.applicationhistory_set.get(status_new=190)

    payload = {
        'application_xid': application.application_xid,
        'email': application.email,
        'dob': format_date(application.dob, 'ddMMyy', locale='id_ID'),
        'company': company.id,
        'form_type': EFWebFormType.MASTER_AGREEMENT
    }

    access_token = encode_jwt_token(payload)
    EmFinancingWFAccessToken.objects.create(email=application.email,
                                            token=access_token, company=company,
                                            form_type=EFWebFormType.MASTER_AGREEMENT,
                                            limit_token_creation=0)

    base_julo_web_url = settings.JULO_WEB_URL
    if settings.ENVIRONMENT == 'staging':
        base_julo_web_url = "https://app-staging2.julo.co.id"

    context = {
        'fullname': application.fullname_with_title,
        'account_set_limit': display_rupiah(approved_limit),
        'cdate_190': x190_history.cdate,
        'company_name': company_name,
        'provision_fee': provision_fee,
        'interest': interest,
        'max_tenor': max_tenor,
        'url': '{}/ef-pilot/{}?token={}'.format(
            base_julo_web_url, 'master-agreement',
            access_token
        )
    }

    email_template = render_to_string('email_template_pilot_ef_sign_master_agreement.html', context=context)
    email_from = "ops.employee_financing@julo.co.id"
    email_to = application.email
    subject = "{} - Pengajuan Kredit Limit JULO telah disetujui, mohon melanjutkan untuk tanda tangan perjanjian".format(
        application.email)

    julo_email_client = get_partnership_email_client()

    msg = email_template
    julo_email_client.send_email(
        subject, msg, email_to, email_from=email_from,
        content_type='text/html')
    EmailHistory.objects.create(
        customer_id=application.customer_id,
        application_id=application.id,
        to_email=email_to,
        subject=subject,
        message_content=msg,
        template_code='email_template_pilot_ef_sign_master_agreement'
    )
