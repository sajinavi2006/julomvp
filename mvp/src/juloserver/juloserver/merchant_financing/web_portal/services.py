import logging
import os

from django.conf import settings

from juloserver.julo.utils import upload_file_as_bytes_to_oss
from juloserver.partnership.constants import (
    SPHPOutputType,
    PartnershipImageType,
    PartnershipImageProductType
)
from juloserver.partnership.models import PartnershipImage
import time
import pyotp
from babel.dates import format_date, format_datetime
from datetime import timedelta, datetime
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from juloserver.julo.constants import VendorConst
from juloserver.julo.models import (
    OtpRequest,
    SmsHistory,
    MobileFeatureSetting,
    Loan,
    PaymentMethod,
    MasterAgreementTemplate,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.tasks import send_sms_otp_token
from juloserver.julo.utils import display_rupiah
from juloserver.otp.constants import SessionTokenAction
from juloserver.pin.constants import OtpResponseMessage
from juloserver.partnership.constants import SPHPOutputType
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.loan.tasks.lender_related import loan_lender_approval_process_task
from juloserver.julo.workflows2.tasks import signature_method_history_task_julo_one

logger = logging.getLogger(__name__)


def process_upload_image(image_data, axiata_temporary_data):
    partnership_image = PartnershipImage()
    image_file = image_data['image_file']
    image_type = image_data['image_type']

    axiata_temporary_data_id = axiata_temporary_data.id

    product_type = PartnershipImageProductType.AXIATA
    partnership_image.image_type = image_type
    partnership_image.application_image_source = axiata_temporary_data_id
    partnership_image.product_type = product_type
    partnership_image.save()

    image_remote_filepath = "/".join(["cust_temporary_axiata" + str(axiata_temporary_data_id), "partnership_image_application", image_file.name])
    upload_file_as_bytes_to_oss(settings.OSS_MEDIA_BUCKET, image_file, image_remote_filepath)

    partnership_image.url = image_remote_filepath
    partnership_image.save()
    
    base_url = settings.BASE_URL.replace('.julofinance.com', '.julo.co.id') 
    url_image_axiata_temporary_data = '{}/api/merchant-financing/web-portal/view-image?image={}'.format(base_url, partnership_image.url)

    if image_type == PartnershipImageType.KTP_SELF:
        axiata_temporary_data.update_safely(
            ktp_image=url_image_axiata_temporary_data,
        )
    elif image_type == PartnershipImageType.SELFIE:
        axiata_temporary_data.update_safely(
            selfie_image=url_image_axiata_temporary_data,
        )

    logger.info(
        {
            "status": "successfull upload image to s3",
            "image_remote_filepath": image_remote_filepath,
            "application_id": partnership_image.application_image_source,
            "image_type": partnership_image.image_type,
        }
    )
    image_path = partnership_image.image.path
    
    # Delete a local file
    if os.path.isfile(image_path):
        logger.info(
            {
                "action": "deleting_local_file",
                "image_path": partnership_image.image.path,
                "application_id": partnership_image.application_image_source,
                "image_type": partnership_image.image_type,
            }
        )
        partnership_image.image.delete()
    
    return partnership_image


def web_portal_send_sms_otp(
    phone_number,
    action_type = SessionTokenAction.PHONE_REGISTER,
    identifier_id = None
):
    mfs = MobileFeatureSetting.objects.get_or_none(feature_name='mobile_phone_1_otp')
    if not mfs.is_active:
        logger.error(
            {
                'action': 'axiata_mobile_feature_settings_mobile_phone_1_otp_not_active',
                'message': 'Mobile feature setting mobile_phone_1_otp is not active',
            }
        )

        data = {
            "success": True,
            "content": {
                "active": mfs.is_active,
                "parameters": mfs.parameters,
                "message": "Verifikasi kode tidak aktif",
            },
        }
        return data

    existing_otp_request = (
        OtpRequest.objects.filter(
            is_used=False,
            phone_number=phone_number,
            action_type=action_type,
        )
        .order_by('id')
        .last()
    )

    change_sms_provide = False
    curr_time = timezone.localtime(timezone.now())
    otp_wait_seconds = mfs.parameters['wait_time_seconds']
    otp_max_request = mfs.parameters['otp_max_request']
    otp_resend_time = mfs.parameters['otp_resend_time']
    data = {
        "otp_content": {
            "parameters": {
                'otp_max_request': otp_max_request,
                'wait_time_seconds': otp_wait_seconds,
                'otp_resend_time': otp_resend_time,
            },
            "message": OtpResponseMessage.SUCCESS,
            "expired_time": None,
            "resend_time": None,
            "otp_max_request": otp_max_request,
            "retry_count": 0,
            "current_time": curr_time,
        }
    }
    if existing_otp_request and existing_otp_request.is_active:
        sms_history = existing_otp_request.sms_history
        prev_time = sms_history.cdate if sms_history else existing_otp_request.cdate
        expired_time = timezone.localtime(existing_otp_request.cdate) + timedelta(
            seconds=otp_wait_seconds
        )
        resend_time = timezone.localtime(prev_time) + timedelta(seconds=otp_resend_time)
        retry_count = (
            SmsHistory.objects.filter(cdate__gte=existing_otp_request.cdate)
            .exclude(status='UNDELIV')
            .count()
        )
        retry_count += 1

        data['otp_content']['expired_time'] = expired_time
        data['otp_content']['resend_time'] = resend_time
        data['otp_content']['retry_count'] = retry_count
        if sms_history and sms_history.status == 'Rejected':
            data['otp_content']['resend_time'] = expired_time
            data['otp_content']['message'] = OtpResponseMessage.FAILED
            data['otp_send_sms_status'] = False
            logger.warning(
                'sms send is rejected, phone_number={}, otp_request_id={}'.format(
                    phone_number, existing_otp_request.id
                )
            )
            return data
        if retry_count > otp_max_request:
            data['otp_content']['message'] = OtpResponseMessage.FAILED
            data['otp_send_sms_status'] = False
            logger.warning(
                'exceeded the max request, '
                'phone_number={}, otp_request_id={}, retry_count={}, '
                'otp_max_request={}'.format(
                    phone_number, existing_otp_request.id, retry_count, otp_max_request
                )
            )
            return data

        if curr_time < resend_time:
            data['otp_content']['message'] = OtpResponseMessage.FAILED
            data['otp_send_sms_status'] = False
            logger.warning(
                'requested OTP less than resend time, '
                'phone_number={}, otp_request_id={}, current_time={}, '
                'resend_time={}'.format(
                    phone_number, existing_otp_request.id, curr_time, resend_time
                )
            )
            return data

        if not sms_history:
            change_sms_provide = True
        else:
            if (
                curr_time > resend_time
                and sms_history
                and sms_history.comms_provider
                and sms_history.comms_provider.provider_name
            ):
                if sms_history.comms_provider.provider_name.lower() == VendorConst.MONTY:
                    change_sms_provide = True

        otp_request = existing_otp_request
    else:
        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
        postfixed_request_id = str(phone_number) + str(int(time.time()))
        otp = str(hotp.at(int(postfixed_request_id)))

        otp_request = OtpRequest.objects.create(
            request_id=postfixed_request_id,
            otp_token=otp,
            phone_number=phone_number,
            action_type=action_type,
        )
        data['otp_content']['expired_time'] = timezone.localtime(otp_request.cdate) + timedelta(
            seconds=otp_wait_seconds
        )
        data['otp_content']['retry_count'] = 1
        data['otp_content']['message'] = OtpResponseMessage.SUCCESS

    text_message = render_to_string(
        'sms_otp_token_application.txt', context={'otp_token': otp_request.otp_token}
    )

    send_sms_otp_token.delay(
        phone_number, text_message, identifier_id, otp_request.id, change_sms_provide
    )
    data['otp_content']['resend_time'] = timezone.localtime(timezone.now()) + timedelta(
        seconds=otp_resend_time
    )

    return data


def web_portal_verify_sms_otp(request_data):
    mfs = MobileFeatureSetting.objects.get_or_none(feature_name='mobile_phone_1_otp')
    if not mfs.is_active:
        logger.error(
            {
                'action': 'axiata_mobile_feature_settings_mobile_phone_1_otp_not_active',
                'message': 'Mobile feature setting mobile_phone_1_otp is not active',
            }
        )

        data = {
            "success": True,
            "content": {
                "active": mfs.is_active,
                "parameters": mfs.parameters,
                "message": "Verifikasi kode tidak aktif",
            },
        }
        return data

    otp_token = request_data.get('otp_token')
    phone_number = request_data.get('phone_number')
    otp_data = OtpRequest.objects.filter(
        phone_number=phone_number, otp_token=otp_token, is_used=False,
        action_type=SessionTokenAction.PHONE_REGISTER
    ).last()
    data = {
        "success": False,
        "content": {
            "message": "Kode verifikasi tidak valid",
        },
    }
    if not otp_data:
        return data

    hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
    valid_token = hotp.verify(otp_token, int(otp_data.request_id))
    if not valid_token:
        return data

    if not otp_data.is_active:
        data = {
            "success": False,
            "content": {
                "message": "Kode verifikasi kadaluarsa",
            },
        }
        return data

    otp_data.is_used = True
    otp_data.save()
    data = {
        "success": True,
        "content": {
            "message": "Kode verifikasi berhasil diverifikasi",
        },
    }
    return data


def get_web_portal_sphp_template(loan_id, type = 'axiata'):
    from juloserver.loan.services.sphp import get_loan_type_sphp_content

    loan = Loan.objects.get_or_none(pk=loan_id)

    if not loan:
        return None
    loan_type = get_loan_type_sphp_content(loan)
    lender = loan.lender
    pks_number = '1.JTF.201707'
    if lender and lender.pks_number:
        pks_number = lender.pks_number
    sphp_date = loan.sphp_sent_ts

    if loan.application:
        application = loan.application
    else:
        application = loan.account.application_set.last()

    context = {
        'loan': loan,
        'application': application,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'full_address': application.full_address,
        'loan_amount': display_rupiah(loan.loan_amount),
        'late_fee_amount': display_rupiah(loan.late_fee_amount),
        'julo_bank_name': loan.julo_bank_name,
        'julo_bank_code': '-',
        'julo_bank_account_number': loan.julo_bank_account_number,
        'date_today': format_date(sphp_date, 'd MMMM yyyy', locale='id_ID'),
        'background_image': settings.SPHP_STATIC_FILE_PATH + 'julo-a-4@3x.png',
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'agreement_letter_number': pks_number,
        'loan_type': loan_type,
    }

    if 'bca' not in loan.julo_bank_name.lower():
        payment_method = PaymentMethod.objects.filter(
            virtual_account=loan.julo_bank_account_number
        ).first()
        if payment_method:
            context['julo_bank_code'] = payment_method.bank_code
    payments = loan.payment_set.exclude(is_restructured=True).order_by('id')
    for payment in payments.iterator():
        payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
        payment.due_amount = display_rupiah(payment.due_amount + payment.paid_amount)

    context['payments'] = payments
    context['max_total_late_fee_amount'] = display_rupiah(loan.max_total_late_fee_amount)
    context['provision_fee_amount'] = display_rupiah(loan.provision_fee())
    context['interest_rate'] = '{}%'.format(loan.interest_percent_monthly())

    if type == SPHPOutputType.AXIATA:
        template = render_to_string('axiata_sphp_document.html', context=context)

    return template


def get_web_portal_agreement(loan, show_provider_signature = True, use_fund_transfer_ts = False):
    axiata_template = MasterAgreementTemplate.objects.filter(
        product_name=PartnerConstant.AXIATA_PARTNER, is_active=True
    ).last()

    content = get_web_portal_agreement_content(loan)

    if use_fund_transfer_ts:
        if loan.fund_transfer_ts:
            content['date_today'] = format_datetime(loan.fund_transfer_ts, "d MMMM yyyy", locale='id_ID')
        else:
            content['date_today'] = format_datetime(loan.cdate, "d MMMM yyyy", locale='id_ID')

    application = loan.application
    axiata_customer_data = application.axiatacustomerdata_set.last()

    customer_name = content['customer_name']

    if not axiata_template:
        logger.error(
            {
                'action_view': 'web_portal_combined_master_agreement_with_skrtp_template',
                'data': {},
                'errors': 'Template tidak ditemukan loan_xid: {} - {}'.format(
                    loan.loan_xid
                ),
            }
        )
        return False

    agreement_template = axiata_template.parameters
    if len(agreement_template) == 0:
        logger.error(
            {
                'action_view': 'web_portal_combined_master_agreement_with_skrtp_template',
                'data': {},
                'errors': 'Body content tidak ada loan_xid: {} = {}'.format(
                    loan.loan_xid
                ),
            }
        )
        return False

    today = datetime.now()
    if use_fund_transfer_ts:
        if loan.fund_transfer_ts:
            today = loan.fund_transfer_ts
        else:
            today = loan.cdate

    signature_today = format_datetime(today, "d MMMM yyyy", locale='id_ID')
    if show_provider_signature:
        signature = (
            '<table border="0" cellpadding="1" cellspacing="1" style="border:none;">'
            '<tbody><tr><td style="width: 50%; text-align: left"></td><td></td>'
            '<td style="width: 50%; text-align: right"></td></tr><tr><td></td>'
            '<td></td><td>'
            '<p style="text-align:right">Jakarta, ' + signature_today + '</p>'
            '</td></tr><tr><td><p style="text-align:left"><strong>Penerima Dana</strong></p>'
            '</td>'
            '<td></td>'
            '<td>'
            '<p style="text-align:right"><strong>Pemberi Dana</strong></p>'
            '</td>'
            '</tr>'
            '<tr>'
            '<td></td>'
            '<td></td>'
            '<td><p style="text-align:right"><strong>PT Julo Teknologi Perdana</strong></p></td>'
            '</tr>'
            '<td><p id="sign"><span>'
            '' + customer_name + '</span></p></td>'
            '<td></td>'
            '<td style="text-align:right">'
            '<p id="sign"><span>H. Sebastian<span></p>'
            '</td>'
            '<tr>'
            '<td><p style="text-align:left">' + customer_name + '</p></td>'
            '<td></td>'
            '<td style="text-align:right"><p>H. Sebastian</p></td>'
            '</tr>'
            '<tr>'
            '<td></td>'
            '<td></td>'
            '<td style="text-align:right"><p>Kuasa Direktur</p></td>'
            '<tr>'
            '</tbody>'
            '</table>'
        )
        css = """
            <link href="https://fonts.googleapis.com/css?family=Pinyon Script" rel="stylesheet">
            <style>
                @font-face {
                    font-family: 'Pinyon Script';
                    src: url('misc_files/fonts/PinyonScript-Regular.ttf')
                }
                #sign {
                    font-family: 'Pinyon Script';
                    font-style: normal;
                    font-weight: 400;
                    font-size: 18.3317px;
                    line-height: 23px;
                }
            </style>
        """
    else:
        signature = (
            '<table border="0" cellpadding="1" cellspacing="1" style="border:none;">'
            '<tbody><tr><td style="width: 50%; text-align: left"></td><td></td>'
            '<td style="width: 50%; text-align: right"></td></tr><tr><td></td>'
            '<td></td><td>'
            '<p style="text-align:right">Jakarta, ' + signature_today + '</p>'
            '</td></tr><tr><td><p style="text-align:left"><strong>Penerima Dana</strong></p>'
            '</td>'
            '<td></td>'
            '<td>'
            '<p style="text-align:right"><strong>Pemberi Dana</strong></p>'
            '</td>'
            '</tr>'
            '<tr>'
            '<td></td>'
            '<td></td>'
            '<td><p style="text-align:right"><strong>PT Julo Teknologi Perdana</strong></p></td>'
            '</tr>'
            '<td><p id="sign"><span>'
            '' + customer_name + '</span></p></td>'
            '<td></td>'
            '<td style="text-align:right">'
            '<p id="sign"><span><span></p>'
            '</td>'
            '<tr>'
            '<td><p style="text-align:left">' + customer_name + '</p></td>'
            '<td></td>'
            '<td style="text-align:right"><p>H. Sebastian</p></td>'
            '</tr>'
            '<tr>'
            '<td></td>'
            '<td></td>'
            '<td style="text-align:right"><p>Kuasa Direktur</p></td>'
            '<tr>'
            '</tbody>'
            '</table>'
        )
        css = """
            <link href="https://fonts.googleapis.com/css?family=Pinyon Script" rel="stylesheet">
            <style>
                @font-face {
                    font-family: 'Pinyon Script';
                    src: url('misc_files/fonts/PinyonScript-Regular.ttf')
                }
                #sign {
                    font-family: 'Pinyon Script';
                    font-style: normal;
                    font-weight: 400;
                    font-size: 18.3317px;
                    line-height: 23px;
                }
            </style>
        """

    tenures = 'Bulan'
    if axiata_customer_data.loan_duration_unit == 'Days':
        tenures = 'Hari'
    elif axiata_customer_data.loan_duration_unit == 'Weeks':
        tenures = 'Minggu'

    loan_duration = '{} {}'.format(
        axiata_customer_data.loan_duration, tenures
    )

    axiata_content = agreement_template.format(
        application_xid=content['application_xid'],
        date_today=content['date_today'],
        customer_name=content['customer_name'],
        dob=content['dob'],
        customer_nik=content['customer_nik'],
        customer_phone=content['customer_phone'],
        full_address=content['full_address'],
        partner_email=content['partner_email'],
        loan_xid=content['loan_xid'],
        loan_amount=content['loan_amount'],
        late_fee_amount=content['late_fee_amount'],
        julo_bank_name=content['julo_bank_name'],
        julo_bank_code=content['julo_bank_code'],
        julo_bank_account_number=content['julo_bank_account_number'],
        show_payments=content['show_payments'],
        maximum_late_fee_amount=content['maximum_late_fee_amount'],
        provision_amount=content['provision_amount'],
        interest_rate=content['interest_rate'],
        signature=signature,
        loan_duration=loan_duration,
    )

    return css + axiata_content


def get_web_portal_agreement_content(loan):
    from juloserver.julo.banks import BankCodes

    application = loan.application
    customer = loan.customer
    axiata_customer_data = application.axiatacustomerdata_set.last()

    today = timezone.localtime(timezone.now()).date()
    content = {
        'application_xid': application.application_xid,
        'date_today': format_datetime(today, "d MMMM yyyy", locale='id_ID'),
        'customer_name': customer.fullname,
        'dob': format_datetime(application.dob, "d MMMM yyyy", locale='id_ID'),
        'customer_nik': application.ktp,
        'customer_phone': application.mobile_phone_1,
        'full_address': application.full_address,
        'partner_email': application.partner.email,
        'loan_xid': loan.loan_xid,
        'loan_amount': display_rupiah(loan.loan_amount),
        'late_fee_amount': display_rupiah(loan.late_fee_amount),
        'julo_bank_name': loan.julo_bank_name,
        'julo_bank_code': BankCodes.BCA,
        'julo_bank_account_number': loan.julo_bank_account_number,
    }

    if 'bca' not in loan.julo_bank_name.lower():
        payment_method = PaymentMethod.objects.filter(
            virtual_account=loan.julo_bank_account_number
        ).first()
        if payment_method:
            content['julo_bank_code'] = payment_method.bank_code

    payments = loan.payment_set.exclude(is_restructured=True).order_by('id')
    for payment in payments.iterator():
        payment.due_amount = payment.due_amount + payment.paid_amount

    payment_result = []
    index = 0

    table_html_tag = (
        '<table style="width: 100%;margin: 0 auto;">'
        '<tbody>'
        '<tr>'
        '<th style="text-align:center;padding: 10px;text-align: left;">'
        '<p style="text-align:center"><strong>Cicilan</strong></p>'
        '</th>'
        '<th style="text-align:center;padding: 10px;text-align: left;">'
        '<p style="text-align:center"><strong>Jumlah</strong></p>'
        '</th>'
        '<th style="text-align:center;padding: 10px;text-align: left;">'
        '<p style="text-align:center"><strong>Jatuh Tempo</strong></p>'
        '</th>'
        '</tr>'
    )
    payment_result.append(table_html_tag)

    for payment in payments:
        index += 1
        format_due_date = format_date(payment.due_date, 'd MMMM yyyy', locale='id_ID')
        html_tag = (
            '<tr>'
            '<td style="text-align:center;padding: 10px;text-align: left;">'
            '<p style="text-align:center">' + str(index) + '</p></td>'
            '<td style="text-align:center;padding: 10px;text-align: left;">'
            '<p style="text-align:center">' + display_rupiah(payment.due_amount) + '</p></td>'
            '<td style="text-align:center;padding: 10px;text-align: left;">'
            '<p style="text-align:center">' + format_due_date + '</p></td></tr>'
        )
        payment_result.append(html_tag)

    end_table_tag = '</tbody></table>'
    payment_result.append(end_table_tag)

    show_payments = ''.join(payment_result)
    content['show_payments'] = show_payments
    content['maximum_late_fee_amount'] = display_rupiah(loan.max_total_late_fee_amount)
    content['provision_amount'] = display_rupiah(loan.provision_fee())
    content['interest_rate'] = '{}%'.format(axiata_customer_data.interest_rate)

    return content


def hold_loan_status_to_211(loan, signature_method):
    new_loan_status = LoanStatusCodes.LENDER_APPROVAL
    user = loan.customer.user
    signature_method_history_task_julo_one(loan.id, signature_method)
    loan.refresh_from_db()
    if loan.status == LoanStatusCodes.LENDER_APPROVAL:
        return new_loan_status

    update_loan_status_and_loan_history(loan.id,
                                        new_status_code=new_loan_status,
                                        change_by_id=user.id,
                                        change_reason="Digital signature succeed"
                                        )
    loan.update_safely(sphp_accepted_ts=timezone.now())
    loan_lender_approval_process_task.delay(loan.id)
    return new_loan_status
