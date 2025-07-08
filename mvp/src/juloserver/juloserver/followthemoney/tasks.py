import time
from future import standard_library
standard_library.install_aliases()
from builtins import str
import logging
import os
import pdfkit
import tempfile
from PyPDF2 import PdfFileReader
import pandas as pd

from xhtml2pdf import pisa
from datetime import timedelta

from celery import task
from django.conf import settings
from django.db.models import Sum
from django.db import transaction

from django.template.loader import render_to_string
from django.forms.models import model_to_dict
from django.contrib.auth.models import User

from juloserver.grab.utils import GrabUtils
from juloserver.julo.clients import (
    get_julo_repayment_bca_client,
    get_julo_email_client,
    get_julo_sentry_client,
    get_julo_digisign_client,
    get_julo_xendit_client,
)

from juloserver.julo.tasks import upload_document
from juloserver.julo.exceptions import JuloException
from juloserver.julo.product_lines import ProductLineCodes

from juloserver.julo.services import process_application_status_change, get_sphp_template
from juloserver.loan.services.views_related import get_sphp_template_grab
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
)
from juloserver.julo.models import (
    Partner,
    EmailHistory,
    Document,
    Application,
    Loan,
    Payment,
    ApplicationHistory,
    ProductLine,
    FeatureSetting,
    MobileFeatureSetting,
    LoanHistory,
)
from juloserver.monitors.notifications import (
    send_message_normal_format,
    send_message_normal_format_to_users,
)
from .services import (
    get_outstanding_loans_by_lender,
    get_transaction_detail,
    get_next_status_by_disbursement_method,
    get_pusdafil_dataframe_from_gdrive,
    process_lender_repayment_dataframe,
    upload_pusdafil_error_to_gdrive,
    upload_pusdafil_partial_error_to_gdrive,
    upload_dataframe_to_gdrive,
    delete_data_from_gdrive,
)
from juloserver.paylater.models import DisbursementSummary
from juloserver.portal.core.templatetags.unit import format_rupiahs

from django.utils import timezone
from datetime import datetime
from dateutil.relativedelta import relativedelta
from juloserver.followthemoney.models import (
    LenderBucket,
    LenderApproval,
    LenderBalanceCurrent,
    LenderBalanceHistory,
    LenderCurrent,
    LoanWriteOff,
    LenderTransactionType,
    LenderDisbursementMethod,
    LenderSignature,
    LenderReversalTransaction,
    LenderTransaction,
    LenderTransactionMapping,
    LoanLenderHistory,
    LenderRepaymentDetailProcessLog,
)

from juloserver.followthemoney.services import (
    reassign_lender,
    get_loan_agreement_template,
    get_summary_loan_agreement_template,
    count_reconcile_transaction,
    create_repayment_data,
    new_repayment_transaction,
    get_repayment_transaction_data,
    generate_group_id,
    reassign_lender_julo_one,
    LenderAgreementLenderSignature,
    LenderAgreementProviderSignature,
    get_signature_key_config,
)

from juloserver.followthemoney.constants import (
    SnapshotType,
    LenderTransactionTypeConst,
    LoanWriteOffPeriodConst,
    LenderRepaymentTransactionStatus,
    LenderRepaymentTransferType,
    LenderReversalTransactionConst,
    PusdafilLenderProcessStatusConst,
)

from juloserver.followthemoney.utils import split_total_repayment_amount
from juloserver.monitors.notifications import get_slack_bot_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.ecommerce.juloshop_service import get_juloshop_transaction_by_loan
from django.db import models

from juloserver.credit_card.tasks.transaction_tasks import assign_loan_credit_card_to_lender_task
from juloserver.customer_module.services.digital_signature import DigitalSignature
from juloserver.loan.utils import chunker
from juloserver.loan.tasks.sphp import send_email_for_skrtp_regeneration
from juloserver.moengage.services.use_cases import send_event_attributes_for_skrtp_regeneration
from juloserver.channeling_loan.services.general_services import (
    is_block_regenerate_document_ars_config_active,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(queue="loan_low")
def send_email_set_password(lender_id, reset_password=False):
    lender = LenderCurrent.objects.get_or_none(pk=lender_id)

    context = {
        'company_name': lender.lender_name,
        'username': lender.user.username
    }
    subject = 'Hi Lender please set new password'
    section = 'set_password'

    if reset_password:
        subject = 'Lender reset password'
        section = 'reset_password'

    context['link_set_password'] = '{}{}/{}'.format(
        settings.FOLLOW_THE_MONEY_URL, section, lender.user.auth_expiry_token.key)

    template_code = 'email_{}_followthemoney'.format(section)
    template = '{}.html'.format(template_code)
    msg = render_to_string(template, context=context)

    julo_email_client = get_julo_email_client()
    status, body, headers = julo_email_client.send_email(subject,
        msg, lender.user.email, 'cs@julofinance.com')

    logger.info({
        'action': template_code,
        'lender_id': lender_id,
    })
    # record email history
    message_id = headers['X-Message-Id']
    EmailHistory.objects.create(
        lender=lender,
        sg_message_id=message_id,
        to_email=lender.user.email,
        subject=subject,
        message_content=msg,
        template_code=template_code,
    )

@task(queue="loan_low")
def auto_reject_bucket(lender_bucket_id):
    lender_bucket = LenderBucket.objects.get_or_none(pk=lender_bucket_id)

    if lender_bucket.is_active:
        app_ids = lender_bucket.application_ids
        approved = app_ids['approved']

        # Change Lender
        for approve in approved:
            reassign_lender(approve)

        # Set lender bucket to inactive
        lender_bucket.update_safely(is_active = False)

@task(queue="loan_high")
def generate_lender_loan_agreement(application_id):
    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        logger.error({
            'action_view': 'generate_lender_loan_agreement',
            'data': {'application_id': application_id},
            'errors': "Application tidak ditemukan."
        })
        return

    try:
        document = Document.objects.get_or_none(document_source=application_id,
                                                document_type="lender_sphp")
        if document:
            logger.error({
                'action_view': 'generate_lender_loan_agreement',
                'data': {'application_id': application_id, 'document': document.filename},
                'errors': "lender loan agreement has found"
            })
            return

        lender = application.loan.lender
        body = get_loan_agreement_template(application, lender)
        if not body:
            logger.error({
                'action_view': 'generate_lender_loan_agreement',
                'data': {'application_id': application_id},
                'errors': "Template tidak ditemukan."
            })
            return
        filename = 'perjanjian_pinjaman-{}.pdf'.format(
            application.application_xid
        )
        file_path = os.path.join(tempfile.gettempdir(), filename )

        file = open(file_path, "w+b")
        pdf = pisa.CreatePDF(body, dest=file, encoding="UTF-8")
        file.close()

        if pdf.err:
            logger.error({
                'action_view': 'generate_lender_loan_agreement',
                'data': {'application_id': application_id},
                'errors': "Failed to create PDF"
            })
            return

        lla = Document.objects.create(document_source=application.id,
            document_type='lender_sphp',
            filename=filename,
            application_xid=application.application_xid)

        logger.info({
            'action_view': 'generate_lender_loan_agreement',
            'data': {'application_id': application_id, 'document_id': lla.id},
            'message': "success create PDF"
        })

        upload_document(lla.id, file_path)

    except Exception as e:
        logger.error({
            'action_view': 'FollowTheMoney - generate_lender_loan_agreement',
            'data': {'application_id': application_id},
            'errors': str(e)
        })
        JuloException(e)

@task(queue="loan_high")
def partner_bulk_disbursement():
    from juloserver.disbursement.models import Disbursement

    today = timezone.localtime(timezone.now())
    yesterday = today - relativedelta(days=1)

    application_ids = ApplicationHistory.objects.filter(cdate__gte=yesterday,
        cdate__lt=today,
        status_new=ApplicationStatusCodes.BULK_DISBURSAL_ONGOING
        ).values_list('application_id', flat=True)

    applications = Application.objects.filter(pk__in=application_ids,
        application_status=ApplicationStatusCodes.BULK_DISBURSAL_ONGOING
        )

    applications_distinct = applications.distinct(
        'loan__partner', 'product_line'
        ).values('loan__partner', 'product_line')

    if applications:
        yesterday = yesterday.date()
        for _filter in applications_distinct:
            product_line = ProductLine.objects.get_or_none(pk=_filter['product_line'])
            partner = Partner.objects.get_or_none(pk=_filter['loan__partner'])

            if partner and product_line:
                applications_filter = applications.filter(**_filter)
                applications_ids = applications_filter.values_list('id', flat=True)
                applications_amount = applications_filter.aggregate(total=models.Sum('loan__loan_disbursement_amount'))
                applications_debt = 0
                if applications_amount['total']:
                    applications_debt = applications_amount['total']

                _filter['transaction_date'] = yesterday
                _filter['partner'] = _filter['loan__partner']

                if _filter.get('loan__partner'):
                    del _filter['loan__partner']

                external_id = "{}{}{}".format(str(partner.id), yesterday, str(product_line.product_line_code))
                external_id = external_id.replace("-", "")

                disburse_xid = "{}{}".format(external_id, str(int(applications_debt))[-3:])
                disbursement_id = None

                with transaction.atomic():
                    disbursement = Disbursement.objects.select_for_update().filter(external_id=external_id).first()
                    if disbursement:
                        disbursement_id = disbursement.id
                        disbursement.external_id=disburse_xid
                        disbursement.save(update_fields=['external_id'])
                        disbursement.refresh_from_db()

                summary = DisbursementSummary.objects.filter(**_filter).first()

                if not summary:
                    DisbursementSummary.objects.create(
                        transaction_date=yesterday,
                        transaction_count=len(applications_ids),
                        transaction_ids=list(applications_ids),
                        transaction_amount=applications_debt,
                        disburse_xid=int(disburse_xid),
                        partner=partner,
                        product_line=product_line,
                        disbursement_id=disbursement_id
                    )
                else:
                    summary.transaction_date = yesterday
                    summary.transaction_count = len(applications_ids)
                    summary.transaction_ids = list(applications_ids)
                    summary.transaction_amount = applications_debt
                    summary.partner = partner
                    summary.product_line = product_line
                    summary.save()

@task(queue="loan_high")
def generate_summary_lender_loan_agreement(
    lender_bucket_id, use_fund_transfer=False, is_new_generate=False, is_for_ar_switching=False
):
    logger_action_view = 'juloserver.followthemoney.tasks.generate_summary_lender_loan_agreement'

    if is_block_regenerate_document_ars_config_active() and is_for_ar_switching:
        logger.info(
            {
                'action_view': logger_action_view,
                'data': {'lender_bucket_id': lender_bucket_id},
                'message': "blocked from regenerate document due to ar switching",
            }
        )
        return

    digisign_client = get_julo_digisign_client()
    lender_bucket = LenderBucket.objects.get_or_none(pk=lender_bucket_id)
    if not lender_bucket:
        logger.error(
            {
                'action_view': logger_action_view,
                'data': {'lender_bucket_id': lender_bucket_id},
                'errors': "LenderBucket tidak ditemukan.",
            }
        )
        return

    try:
        document = Document.objects.get_or_none(document_source=lender_bucket_id,
                                                document_type="summary_lender_sphp")
        if document:
            logger.error(
                {
                    'action_view': logger_action_view,
                    'data': {'lender_bucket_id': lender_bucket_id, 'document': document.filename},
                    'errors': "summary lender loan agreement has found",
                }
            )
            return

        user = lender_bucket.partner.user
        lender = user.lendercurrent
        body = get_summary_loan_agreement_template(lender_bucket, lender, use_fund_transfer)

        if not body:
            logger.error(
                {
                    'action_view': logger_action_view,
                    'data': {'lender_bucket_id': lender_bucket_id},
                    'errors': "Template tidak ditemukan.",
                }
            )
            return
        filename = 'rangkuman_perjanjian_pinjaman-{}{}.pdf'.format(
            lender_bucket.lender_bucket_xid,
            '-new' if is_new_generate else '',
        )
        file_path = os.path.join(tempfile.gettempdir(), filename )

        try:
            pdfkit.from_string(body, file_path)
        except Exception as e:
            logger.error(
                {
                    'action_view': logger_action_view,
                    'data': {'lender_bucket_id': lender_bucket_id},
                    'errors': "Failed to create PDF",
                }
            )
            return

        user_keys, default_key = get_signature_key_config()
        lender_sign = DigitalSignature.Signer(
            user,
            signature=LenderAgreementLenderSignature,
            key_name="key-{}-{}".format(
                user.id, user_keys[str(user.id)] if str(user.id) in user_keys else default_key
            ),
            for_organization=True,
        )
        provider = User.objects.filter(email='athe.ginting@julo.co.id').last()
        provider_sign = DigitalSignature.Signer(
            provider,
            signature=LenderAgreementProviderSignature,
            key_name="key-{}-{}".format(
                provider.id,
                user_keys[str(provider.id)] if str(provider.id) in user_keys else default_key,
            ),
            for_organization=True,
        )
        file_path = DigitalSignature.Document(file_path)\
            .add_signer(lender_sign)\
            .add_signer(provider_sign)\
            .sign()

        signature = lender_sign.sign(path=file_path)
        summary_lla = Document.objects.create(
            document_source=lender_bucket_id,
            document_type='summary_lender_sphp',
            filename=filename,
            hash_digi_sign=signature['signature'],
            key_id=signature['key_id'],
            accepted_ts=signature['created_at'],
            signature_version=signature['version'],
        )
        lender_sign.record_history(
            summary_lla, action="sign", note="Successfully generate signature in Lender Agreement."
        )

        logger.info(
            {
                'action_view': logger_action_view,
                'data': {'lender_bucket_id': lender_bucket_id, 'document_id': summary_lla.id},
                'message': "success create PDF",
            }
        )

        upload_document(summary_lla.id, file_path, is_bucket=True)

        #upload to digisign
        feature_setting = MobileFeatureSetting.objects.filter(
            feature_name='digisign_mode', is_active=True).last()
        if feature_setting:
            digisign_client.send_lla_document(summary_lla.id, lender.id, lender_bucket_id, filename)

    except Exception as e:
        logger.error(
            {
                'action_view': 'FollowTheMoney - {}'.format(logger_action_view),
                'data': {'lender_bucket_id': lender_bucket_id},
                'errors': str(e),
            }
        )
        JuloException(e)

@task(queue="loan_high")
def generate_sphp(application_id):
    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        logger.error({
            'action_view': 'generate_sphp',
            'data': {'application_id': application_id},
            'errors': "Application tidak ditemukan."
        })
        return

    try:
        document = Document.objects.get_or_none(document_source=application_id,
                                                document_type="sphp_julo")
        if document:
            logger.error({
                'action_view': 'generate_sphp',
                'data': {'application_id': application_id, 'document': document.filename},
                'errors': "sphp has found"
            })
            return

        lender = application.loan.lender
        body = get_sphp_template(application_id)
        if not body:
            logger.error({
                'action_view': 'generate_sphp',
                'data': {'application_id': application_id},
                'errors': "Template tidak ditemukan."
            })
            return
        now = datetime.now()
        filename = '{}_{}_{}_{}.pdf'.format(
            application.fullname,
            application.application_xid,
            now.strftime("%Y%m%d"),
            now.strftime("%H%M%S"))
        file_path = os.path.join(tempfile.gettempdir(), filename )

        try:
            pdfkit.from_string(body, file_path)
        except Exception as e:
            logger.error({
                'action_view': 'generate_sphp',
                'data': {'application_id': application_id},
                'errors': "Failed to create PDF"
            })
            return

        sphp_julo = Document.objects.create(document_source=application.id,
            document_type='sphp_julo',
            filename=filename,
            application_xid=application.application_xid)

        logger.info({
            'action_view': 'generate_sphp',
            'data': {'application_id': application_id, 'document_id': sphp_julo.id},
            'message': "success create PDF"
        })

        upload_document(sphp_julo.id, file_path)

    except Exception as e:
        logger.error({
            'action_view': 'FollowTheMoney - generate_sphp',
            'data': {'application_id': application_id},
            'errors': str(e)
        })
        JuloException(e)


@task(queue="loan_high")
def generate_julo_one_loan_agreement(loan_id, is_new_generate=False, is_for_ar_switching=False):
    from juloserver.loan.services.agreement_related import get_julo_loan_agreement_template

    logger_action_view = 'juloserver.followthemoney.tasks.generate_julo_one_loan_agreement'

    if is_block_regenerate_document_ars_config_active() and is_for_ar_switching:
        logger.info(
            {
                'action_view': logger_action_view,
                'data': {'loan_id': loan_id},
                'message': "blocked from regenerate document due to ar switching",
            }
        )
        return

    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        logger.warning(
            {
                'action_view': logger_action_view,
                'data': {'loan_id': loan_id},
                'errors': "Loan tidak ditemukan.",
            }
        )
        return

    try:
        document = Document.objects.filter(
            document_source=loan_id,
            document_type__in=('sphp_julo', 'skrtp_julo'),
            loan_xid=loan.loan_xid
        )
        is_payment_restructured = loan.payment_set.filter(is_restructured=True).exists()
        if (
            not is_new_generate
            and (
                document
                and not loan.is_credit_card_product
                or (
                    loan.is_credit_card_product
                    and (
                        len(document) >= 2
                        or (len(document) == 1 and not is_payment_restructured)
                    )
                )
            )
        ):
            logger.warning(
                {
                    'action_view': logger_action_view,
                    'data': {'loan_id': loan_id, 'document': document.last().filename},
                    'errors': "sphp has found",
                }
            )
            return

        body, agreement_type, lender_signature, borrower_signature = \
            get_julo_loan_agreement_template(loan_id)
        if not body:
            logger.error(
                {
                    'action_view': logger_action_view,
                    'data': {'loan_id': loan_id},
                    'errors': "Template tidak ditemukan.",
                }
            )
            raise JuloException('SPHP / SKRTP template is not found.')
        now = timezone.localtime(timezone.now())
        if loan.application and loan.application.product_line_code in ProductLineCodes.axiata():
            application = loan.application
        else:
            application = loan.get_application
        filename = '{}_{}{}_{}_{}.pdf'.format(
            application.fullname,
            loan.loan_xid,
            '_new' if is_new_generate else '',
            now.strftime("%Y%m%d"),
            now.strftime("%H%M%S"),
        )
        if not is_new_generate and document and loan.is_credit_card_product:
            filename_only, extension = os.path.splitext(filename)
            filename = '{}_2{}'.format(filename_only, extension)
        file_path = os.path.join(tempfile.gettempdir(), filename)

        try:
            now = time.time()
            pdfkit.from_string(body, file_path)
            time_limit = 2
            elapsed = time.time() - now
            if elapsed > time_limit:
                logger.info(
                    {
                        'action_view': logger_action_view,
                        'data': {'loan_id': loan_id},
                        'message': "PDF rendering takes {} seconds, which is more than the {} seconds limit.".format(
                            elapsed, time_limit
                        ),
                    }
                )
        except Exception as e:
            logger.exception(
                {
                    'action_view': logger_action_view,
                    'data': {'loan_id': loan_id},
                    'errors': "Failed to create PDF",
                }
            )
            raise e

        # generate qris skrtp without digisign
        if loan.is_qris_1_product:
            generate_qris_skrtp_julo(loan, agreement_type, filename, file_path)
            return

        # get num_pages => signing correct number page
        with open(file_path, 'rb') as file:
            reader = PdfFileReader(file)
            num_pages = reader.getNumPages() - 1
            lender_signature.page = num_pages
            borrower_signature.page = num_pages

        user_keys, default_key = get_signature_key_config()
        user = application.customer.user
        borrower_sign = DigitalSignature.Signer(
            user,
            signature=borrower_signature,
            key_name="key-{}-{}".format(
                user.id, user_keys[str(user.id)] if str(user.id) in user_keys else default_key,
            ),
            full_name=application.fullname,
            province=application.address_provinsi or '',
            city=application.address_kabupaten or '',
            address=application.address_street_num or '',
            postal_code=application.address_kodepos or '',
            location='',
        )

        lender = loan.lender
        user_lender = lender.user
        lender_sign = DigitalSignature.Signer(
            user_lender,
            signature=lender_signature,
            key_name="key-{}-{}".format(
                lender.user_id,
                user_keys[str(lender.user_id)] if str(lender.user_id) in user_keys else default_key,
            ),
            for_organization=True,
        )

        file_path = DigitalSignature.Document(file_path)\
            .add_signer(borrower_sign)\
            .add_signer(lender_sign)\
            .sign()

        signature = borrower_sign.sign(path=file_path)
        sphp_or_skrtp_julo = Document.objects.create(
            document_source=loan.id,
            document_type='%s_julo' % agreement_type,
            hash_digi_sign=signature['signature'],
            key_id=signature['key_id'],
            accepted_ts=signature['created_at'],
            filename=filename,
            loan_xid=loan.loan_xid,
            signature_version=signature['version'],
        )
        borrower_sign.record_history(
            sphp_or_skrtp_julo,
            action="sign",
            note="Successfully generate signature in loan agreement.",
        )

        logger.info(
            {
                'action_view': logger_action_view,
                'data': {
                    'loan_id': loan_id,
                    'document_id': sphp_or_skrtp_julo.id,
                    'agreement_type': agreement_type,
                },
                'message': "success create PDF",
            }
        )

        upload_document(sphp_or_skrtp_julo.id, file_path, is_loan=True)
        assign_loan_credit_card_to_lender_task.apply_async(
            (loan.id,), eta=(timezone.localtime(loan.cdate) + timedelta(minutes=5))
        )

    except Exception as e:
        logger.exception(
            {
                'action_view': 'FollowTheMoney - {}'.format(logger_action_view),
                'data': {'loan_id': loan_id},
                'errors': str(e),
            }
        )
        raise e


@task(queue="loan_high")
def generate_sphp_grab(loan_id):
    """
    deprecated method, use trigger_sending_email_sphp in juloserver/grab/communication/email.py instead
    """
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        logger.error({
            'action_view': 'generate_sphp_grab',
            'data': {'loan_id': loan_id},
            'errors': "Loan tidak ditemukan."
        })
        return

    try:
        document = Document.objects.get_or_none(document_source=loan_id,
                                                document_type="sphp_grab")
        if document:
            logger.error({
                'action_view': 'generate_sphp_grab',
                'data': {'loan_id': loan_id, 'document': document.filename},
                'errors': "sphp has found"
            })
            return

        lender = loan.lender
        body = get_sphp_template_grab(loan_id)
        if not body:
            logger.error({
                'action_view': 'generate_sphp_grab',
                'data': {'loan_id': loan_id},
                'errors': "Template tidak ditemukan."
            })
            return
        now = datetime.now()
        application = loan.get_application
        filename = '{}_{}_{}_{}.pdf'.format(
            application.fullname,
            loan.loan_xid,
            now.strftime("%Y%m%d"),
            now.strftime("%H%M%S"))
        file_path = os.path.join(tempfile.gettempdir(), filename )

        try:
            pdfkit.from_string(body, file_path)
        except Exception as e:
            logger.error({
                'action_view': 'generate_sphp_grab',
                'data': {'loan_id': loan_id},
                'errors': "Failed to create PDF"
            })
            return

        # digital signature
        user = application.customer.user
        hash_digi_sign, key_id, accepted_ts = GrabUtils.create_digital_signature(
            user, file_path)
        sphp_grab = Document.objects.create(document_source=loan.id,
                                            document_type='sphp_grab',
                                            filename=filename,
                                            loan_xid=loan.loan_xid,
                                            hash_digi_sign=hash_digi_sign,
                                            key_id=key_id,
                                            accepted_ts=accepted_ts)

        logger.info({
            'action_view': 'generate_sphp_grab',
            'data': {'loan_id': loan_id, 'document_id': sphp_grab.id},
            'message': "success create PDF"
        })

        upload_document(sphp_grab.id, file_path, is_loan=True)

    except Exception as e:
        logger.error({
            'action_view': 'FollowTheMoney - generate_sphp-julo-one',
            'data': {'loan_id': loan_id},
            'errors': str(e)
        })
        JuloException(e)


@task(queue="loan_high")
def approved_application_process_disbursement(application_id, partner_id):
    generate_lender_loan_agreement(application_id)
    target_status = get_next_status_by_disbursement_method(application_id, partner_id)
    if target_status:
        process_application_status_change(
            application_id,
            target_status,
            "Approved by lender via Follow The Money",
        )

@task(queue="loan_high")
def bulk_approved_application_process_disbursement(lenderbucket, signature_method):
    for application_id in lenderbucket.application_ids['approved']:
        approved_application_process_disbursement(application_id, lenderbucket.partner_id)

    #update lendersignature
    lender_signatures = LenderSignature.objects.filter(
        lender_bucket_xid=lenderbucket.lender_bucket_xid
    )
    if lender_signatures:
        lender_signatures.update(
            signature_method=signature_method,
            signed_ts=True
        )

@task(queue="loan_low")
def reset_all_lender_bucket(partner_id):
    partner = Partner.objects.get_or_none(pk=partner_id)
    lender_approval = LenderApproval.objects.get_or_none(partner=partner)
    today = timezone.now()

    if lender_approval:
        in_range = False
        if lender_approval.end_date:
            in_range = (lender_approval.start_date <= today <= lender_approval.end_date)

        in_endless = (today >= lender_approval.start_date and lender_approval.is_endless)
        if lender_approval.is_auto and ( in_range or in_endless ):
            lender_bucket = LenderBucket.objects.filter(partner=partner, is_active=True).last()
            if lender_bucket:
                # Set lender bucket to inactive
                lender_bucket.update_safely(is_active=False,
                    action_time=timezone.now(),
                    action_name="Canceled by Auto Approval")

            applications_165 = Application.objects.filter(
                application_status__status_code=ApplicationStatusCodes.LENDER_APPROVAL,
                loan__partner=partner
            ).order_by("id")
            for application in applications_165:
                try:
                    target_status = ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED
                    lender_disbursement_method = LenderDisbursementMethod.objects.filter(
                        partner=application.loan.partner).first()

                    if lender_disbursement_method:
                        product_lines = eval('ProductLineCodes.{}()'.format(
                            lender_disbursement_method.product_lines))
                        if application.product_line_id in product_lines and lender_disbursement_method.is_bulk:
                            target_status = ApplicationStatusCodes.BULK_DISBURSAL_ONGOING

                    process_application_status_change(application.id,
                        target_status,
                        "Continue By Auto Approval Follow The Money", "followthemoney")
                except Exception as e:
                    sentry_client.captureException()
                    logger.info({
                        'action': 'reset_all_lender_bucket',
                        'data': "{} - {}".format(partner_id, application),
                        'message': str(e)
                    })


@task(queue="loan_high")
def exclude_write_off_loans_from_current_lender_balance():
    loans = get_outstanding_loans_by_lender()
    lenders = LenderCurrent.objects.values('id').all()
    wo_90_loans_dict = {}
    wo_180_loans_dict = {}
    wo_90_loans = LoanWriteOff.objects.filter(wo_period=LoanWriteOffPeriodConst.WO_90)\
                                      .values('id')

    wo_180_loans = LoanWriteOff.objects.filter(wo_period=LoanWriteOffPeriodConst.WO_180)\
                                       .values('id')

    for loan in wo_90_loans:
        wo_90_loans_dict[loan['id']] = {}

    for loan in wo_180_loans:
        wo_180_loans_dict[loan['id']] = {}

    lender_dict = {}

    for lender in lenders:
        lender_dict[lender['id']] = {}
        lender_dict[lender['id']]['outstanding_principal'] = 0
        lender_dict[lender['id']]['outstanding_interest'] = 0
        lender_dict[lender['id']]['paid_principal'] = 0
        lender_dict[lender['id']]['paid_interest'] = 0

    for key, values in list(loans.items()):
        old_outstanding_principal = lender_dict[values['lender_id']]['outstanding_principal']
        old_outstanding_interest = lender_dict[values['lender_id']]['outstanding_interest']
        old_principal_paid = lender_dict[values['lender_id']]['paid_principal']
        old_interest_paid = lender_dict[values['lender_id']]['paid_interest']

        lender_dict[values['lender_id']]['outstanding_principal'] = old_outstanding_principal + \
            values['outstanding_principal_amount']

        lender_dict[values['lender_id']]['outstanding_interest'] = old_outstanding_interest + \
            values['outstanding_interest_amount']

        lender_dict[values['lender_id']]['paid_principal'] = old_principal_paid + \
            values['paid_principal']

        lender_dict[values['lender_id']]['paid_interest'] = old_interest_paid + \
            values['paid_interest']

        wo_date_90 = loans[key].get('wo_date_90')
        wo_date_180 = loans[key].get('wo_date_180')

        if wo_date_90 is not None:
            wo_date = wo_date_90
            wo_period = 90

        if wo_date_180 is not None:
            wo_date = wo_date_180
            wo_period = 180

        if wo_date_90 is not None or wo_date_180 is not None:
            new_loan_dict = {}
            new_loan_dict = values
            new_loan_dict['loan_id'] = key
            new_loan_dict['wo_period'] = wo_period
            new_loan_dict['wo_date'] = wo_date

            if wo_90_loans_dict.get(key) and wo_180_loans_dict.get(key):
                continue

            new_loan_dict.pop('outstanding_principal_amount', None)
            new_loan_dict.pop('outstanding_interest_amount', None)
            new_loan_dict.pop('fund_transfer_ts', None)
            new_loan_dict.pop('lender_id', None)
            new_loan_dict.pop('wo_date_90', None)
            new_loan_dict.pop('wo_date_180', None)
            new_loan_dict.pop('loan_status_code', None)
            new_loan_dict.pop('total_principal_amount', None)
            new_loan_dict.pop('loan_purpose', None)
            new_loan_dict.pop('lla_xid', None)
            new_loan_dict.pop('running_terms_date', None)
            new_loan_dict.pop('loan_duration', None)
            new_loan_dict.pop('loan_principal_amount', None)
            new_loan_dict.pop('paid_yield_amount', None)

            LoanWriteOff.objects.create(**new_loan_dict)

    for key, value in list(lender_dict.items()):
        new_dict = {}
        new_dict = value
        with transaction.atomic():
            lender_balance = LenderBalanceCurrent.objects.select_for_update()\
                                                         .filter(lender_id=key).last()

            if not lender_balance:
                continue

            lender_balance.update_safely(**new_dict)
            updated_lender_balance_dict = lender_balance.__dict__
            updated_lender_balance_dict['snapshot_type'] = SnapshotType.WRITE_OFF
            updated_lender_balance_dict.pop('_state', None)
            updated_lender_balance_dict.pop('id', None)

            fields = set(f.column for f in LenderBalanceHistory._meta.get_fields())
            updated_lender_balance_dict = \
                {k: v for k, v in list(updated_lender_balance_dict.items()) if k in fields}

            LenderBalanceHistory.objects.create(**updated_lender_balance_dict)


@task(queue="loan_high")
def reconcile_lender_balance():
    lender_ids = LenderCurrent.objects.all().values_list('id', flat=True)

    for lender_id in lender_ids:
        task_reconcile_perlender.delay(lender_id)


@task(queue="loan_high")
def task_reconcile_perlender(lender_id):
    with transaction.atomic():
        lender_balance = LenderBalanceCurrent.objects.select_for_update()\
                                             .filter(lender_id=lender_id).last()

        if lender_balance is None:
            return None

        lender_balance_history = LenderBalanceHistory.objects.filter(
            lender_id=lender_id,
            snapshot_type=SnapshotType.RECONCILE)\
            .last()

        since = None
        last_available_balance = 0

        if lender_balance_history:
            since = lender_balance_history.cdate
            last_available_balance = lender_balance_history.available_balance

        transaction_amounts = count_reconcile_transaction(lender_id, since)
        reconcile_available_balance = transaction_amounts + last_available_balance

        lender_balance.update_safely(
            available_balance=reconcile_available_balance
        )

        lender_balance_dict = model_to_dict(lender_balance)

        lender_balance_dict.pop('id', None)
        lender_balance_dict.pop('lender', None)

        lender_balance_dict['snapshot_type'] = SnapshotType.RECONCILE
        lender_balance_dict['lender_id'] = lender_id

        LenderBalanceHistory.objects.create(**lender_balance_dict)

@task(queue="loan_low")
def assign_lenderbucket_xid_to_lendersignature(app_ids, lender_bucket_xid, is_loan=False):
    for app_id in app_ids:
        if is_loan:
            loan = Loan.objects.get_or_none(id=app_id)
        else:
            loan = Loan.objects.get_or_none(application=app_id)
        lender_signature, created = LenderSignature.objects.get_or_create(loan=loan)
        if created:
            logger.info({
                'action': 'assign_lenderbucket_xid_to_lendersignature',
                'lender_signature': lender_signature.id,
                'mesage': 'lender_signature created'
            })

        if lender_signature:
            lender_signature.update_safely(lender_bucket_xid=lender_bucket_xid)

@task(queue="loan_low")
def auto_expired_application_tasks(application_id, lender_id):
    application = Application.objects.get_or_none(pk=application_id)

    if application and application.status == ApplicationStatusCodes.LENDER_APPROVAL:
        loan = application.loan

        if loan.lender and loan.lender.id == lender_id:
            reassign_lender(application_id)


@task(queue="loan_high")
def auto_expired_loan_tasks(loan_id, lender_id):
    ftm_configuration = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.FTM_CONFIGURATION,
        category="followthemoney", is_active=True)
    if not ftm_configuration:
        logger.info({
            'action': 'followthemoney.tasks.auto_expired_loan_tasks',
            'loan_id': loan_id,
            'lender_id': lender_id,
            'message': 'configuration not set'
        })
        return

    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        logger.info({
            'action': 'followthemoney.tasks.auto_expired_loan_tasks',
            'loan_id': loan_id,
            'lender_id': lender_id,
            'message': 'loan not found'
        })
        return

    loan_history = LoanHistory.objects.filter(
        loan=loan, status_new=LoanStatusCodes.LENDER_APPROVAL
    ).last()
    if not loan_history:
        logger.info({
            'action': 'followthemoney.tasks.auto_expired_loan_tasks',
            'loan_id': loan_id,
            'lender_id': lender_id,
            'message': 'loan never move to lender approval status'
        })
        return

    if loan and loan.status != LoanStatusCodes.LENDER_APPROVAL:
        logger.info({
            'action': 'followthemoney.tasks.auto_expired_loan_tasks',
            'loan_id': loan_id,
            'lender_id': lender_id,
            'message': 'loan status not 211'
        })
        return

    date_diff = timezone.localtime(timezone.now()) - timezone.localtime(loan_history.cdate)
    if date_diff.days >= 1:
        update_loan_status_and_loan_history(
            loan_id=loan_id,
            new_status_code=LoanStatusCodes.LENDER_REJECT,
            change_by_id=loan.customer.user.id,
            change_reason="Loan reject by lender",
        )
        return

    get_loan_count = LoanLenderHistory.objects.filter(loan=loan).count()
    if get_loan_count > ftm_configuration.parameters['reassign_count']:
        logger.info({
            'action': 'followthemoney.tasks.auto_expired_loan_tasks',
            'loan_id': loan_id,
            'lender_id': lender_id,
            'message': 'reassign lender already reach maximum number'
        })
        return

    if loan and loan.status == LoanStatusCodes.LENDER_APPROVAL:
        if loan.lender_id == lender_id:
            reassign_lender_julo_one(loan_id)


@task(queue="loan_high")
def repayment_daily_transfer():
    lender_target = LenderCurrent.objects.get(lender_name='jtp')
    data = get_repayment_transaction_data(lender_target, filtering=True)
    if not data:
        return
    split_amount_list = split_total_repayment_amount(data['amount'])
    bca_client = get_julo_repayment_bca_client()
    transaction_list = []

    with transaction.atomic():
        group_data, can_process = get_transaction_detail(lender_target.id)
        if group_data or not can_process:
            return
        max_group_id = generate_group_id(lender_target.id)
        for split_amount in split_amount_list:
            transaction_data = create_repayment_data(split_amount,
                                                     data['cust_account_number'],
                                                     data['bank_name'],
                                                     data['cust_name_in_bank'],
                                                     data['additional_info'],
                                                     LenderRepaymentTransferType.AUTO,
                                                     max_group_id)
            transaction_record = new_repayment_transaction(transaction_data,
                                                           lender=lender_target)
            transaction_list.append(transaction_record)

    for transaction_record in transaction_list:
        try:
            res = bca_client.domestic_transfer(transaction_data['reference_id'],
                                               transaction_record.id,
                                               data['cust_account_number'],
                                               transaction_data['beneficiary_bank_code'],
                                               data['cust_name_in_bank'], transaction_record.amount,
                                               transaction_data['remark'])
        except JuloException as error:
            transaction_record.status = LenderRepaymentTransactionStatus.FAILED
            transaction_record.response_code = str(error)
            transaction_record.save()
            continue
        transaction_record.status = LenderRepaymentTransactionStatus.PENDING
        transaction_record.response_code = res['PPUNumber']
        transaction_record.save()
        continue


@task(queue="loan_high")
def scheduled_retry_for_reversal_payment_insufficient_balance():
    from .services import deduct_lender_reversal_transaction, get_available_balance
    lender_reversal_trxs = LenderReversalTransaction.objects.filter(
        status=LenderReversalTransactionConst.PENDING,
        is_waiting_balance=True
    )
    logger.info({
        'action': 'scheduled_retry_for_reversal_payment_insufficient_balance',
        'lender_reversal_trxs_count': lender_reversal_trxs.count()
    })

    for lender_reversal_trx in lender_reversal_trxs:
        lender_balance = get_available_balance(lender_reversal_trx.source_lender.id)
        sufficient_balance = lender_reversal_trx.amount <= lender_balance

        if sufficient_balance:
            data = {'id': lender_reversal_trx.id, 'loan_desc': lender_reversal_trx.loan_description}
            deduct_lender_reversal_transaction(data)


@task(queue="loan_low")
def send_warning_message_low_balance_amount(lender_name):
    from juloserver.portal.core.templatetags.unit import format_rupiahs

    feature_setting = FeatureSetting.objects.filter(category="disbursement", is_active=True,
        feature_name=FeatureNameConst.NOTIFICATION_BALANCE_AMOUNT).first()
    if not feature_setting:
        return

    lender = LenderCurrent.objects.get_or_none(lender_status="active", lender_name=lender_name)
    if not lender:
        return

    if not lender.lenderbalancecurrent:
        return

    available_balance = lender.lenderbalancecurrent.available_balance
    if available_balance > lender.minimum_balance:
        return

    messages = "*Warning Message*\n"
    setting_env = settings.ENVIRONMENT
    if setting_env != 'prod':
        messages = "*Warning Message (TESTING PURPOSE ONLY FROM %s)*\n" % (setting_env.upper())

    messages += "{0} Disbursement Balance is Low\n balance : {1}\n" \
            "Please do transfer fund immediately!\n\n".format(
                lender.lender_name, format_rupiahs(available_balance, 'no'))

    for user in feature_setting.parameters['users']:
        get_slack_bot_client().api_call("chat.postMessage", channel=user, text=messages)


@task(queue="loan_low")
def send_notification_current_balance_amount():
    from juloserver.portal.core.templatetags.unit import format_rupiahs

    feature_setting = FeatureSetting.objects.filter(category="disbursement", is_active=True,
        feature_name=FeatureNameConst.NOTIFICATION_BALANCE_AMOUNT).first()
    if not feature_setting:
        return

    lenders = LenderCurrent.objects.filter(
        lender_status="active", lender_name__in=LenderCurrent.lender_notification_list())
    messages = "*Warning Message*\n"
    setting_env = settings.ENVIRONMENT
    if setting_env != 'prod':
        messages = "*Warning Message (TESTING PURPOSE ONLY FROM %s)*\n" % (setting_env.upper())
    send_notif = False
    for lender in lenders:
        if not lender.lenderbalancecurrent:
            continue

        available_balance = lender.lenderbalancecurrent.available_balance
        messages += "{0} Disbursement Balance\n balance : {1}\n\n".format(
            lender.lender_name, format_rupiahs(available_balance, 'no'))
        send_notif = True

    if send_notif:
        for user in feature_setting.parameters['users']:
            get_slack_bot_client().api_call("chat.postMessage", channel=user, text=messages)


@task(queue='repayment_high')
def create_lender_transaction_for_reversal_payment(lender_id, amount,
                                                   reference, payment_event,
                                                   different_lender=False, deduct=False):

    lender_balance = LenderBalanceCurrent.objects.filter(lender_id=lender_id).last()
    transaction_type = LenderTransactionType.objects.get(
        transaction_type=LenderTransactionTypeConst.BALANCE_ADJUSTMENT
    )

    lender_transaction = LenderTransaction.objects.create(
        lender_id=lender_id,
        transaction_amount=amount,
        lender_balance_current=lender_balance,
        transaction_type=transaction_type,
        transaction_description=reference
    )
    ltm = LenderTransactionMapping.objects.get(payment_event=payment_event)
    ltm.update_safely(lender_transaction=lender_transaction)

    if different_lender:
        data = {}
        payment = payment_event.payment
        if deduct:
            outstanding_principal = lender_balance.outstanding_principal + payment.paid_principal
            outstanding_interest = lender_balance.outstanding_interest + payment.paid_interest
            paid_principal = lender_balance.paid_principal - payment.paid_principal
            paid_interest = lender_balance.paid_interest - payment.paid_interest
        else:
            outstanding_principal = lender_balance.outstanding_principal - payment.paid_principal
            outstanding_interest = lender_balance.outstanding_interest - payment.paid_interest
            paid_principal = lender_balance.paid_principal + payment.paid_principal
            paid_interest = lender_balance.paid_interest + payment.paid_interest

        data.update({
            'outstanding_principal': outstanding_principal,
            'outstanding_interest': outstanding_interest,
            'paid_principal': paid_principal,
            'paid_interest': paid_interest
        })

        calculate_available_balance.delay(lender_balance.id, SnapshotType.TRANSACTION, **data)


@task(queue='loan_high')
def calculate_available_balance(lender_balance_id, snapshot_type, **lender_balance_kwargs):
    from .services import get_available_balance
    lender_balance = LenderBalanceCurrent.objects.get_or_none(pk=lender_balance_id)
    if not lender_balance:
        raise JuloException("Lender balance current not found")
    is_delay = lender_balance_kwargs.get('is_delay', True)
    loan_amount = lender_balance_kwargs.get('loan_amount', 0)
    repayment_amount = lender_balance_kwargs.get('repayment_amount', 0)
    withdrawal_amount = lender_balance_kwargs.pop('withdrawal_amount', 0)
    available_balance = get_available_balance(lender_balance.lender_id)

    pending_withdrawal = lender_balance.pending_withdrawal + withdrawal_amount

    remaining_balance = available_balance - loan_amount + repayment_amount - pending_withdrawal
    lender_balance_kwargs['available_balance'] = remaining_balance
    lender_balance_kwargs['pending_withdrawal'] = pending_withdrawal

    # Remove unused key
    lender_balance_kwargs.pop('loan_amount', None)
    lender_balance_kwargs.pop('repayment_amount', None)
    lender_balance_kwargs.pop('is_delay', None)

    logger.info({
        'method': 'juloserver.followthemoney.tasks.calculate_available_balance',
        'message': 'start deposit lender balance for {}'.format(lender_balance_id),
    })
    if remaining_balance < 0:
        raise JuloException("Available balance insufficient")

    # Update lender balance
    lender_balance.update_safely(**lender_balance_kwargs)

    # Insert lender balance history
    if is_delay:
        insert_data_into_lender_balance_history.delay(
            lender_balance, pending_withdrawal, snapshot_type, remaining_balance)
    else:
        insert_data_into_lender_balance_history(
            lender_balance, pending_withdrawal, snapshot_type, remaining_balance)

    return available_balance


@task(queue='repayment_high')
def insert_data_into_lender_balance_history(
    lender_balance, pending_withdrawal, snapshot_type, remaining_balance):
    LenderBalanceHistory.objects.create(
        snapshot_type=snapshot_type,
        lender_id=lender_balance.lender_id,
        available_balance=remaining_balance,
        paid_principal=lender_balance.paid_principal,
        paid_interest=lender_balance.paid_interest,
        outstanding_principal=lender_balance.outstanding_principal,
        outstanding_interest=lender_balance.outstanding_interest,
        committed_amount=lender_balance.committed_amount,
        pending_withdrawal=pending_withdrawal,
    )


@task(queue='repayment_high')
def update_lender_balance_current_for_disbursement_async_task(
        loan_id, disbursement_summary=None, lender_transaction_id=None):

    with transaction.atomic():
        loan = Loan.objects.get(pk=loan_id)
        if not loan:
            raise JuloException('Loan not found')

        if disbursement_summary:
            lender = disbursement_summary.partner.user.lendercurrent
            loan_amount = disbursement_summary.disbursement.original_amount
            filter_ = dict(loan__application_id__in=disbursement_summary.transaction_ids)
            disbursement_id = disbursement_summary.disbursement_id

        else:
            lender = loan.lender
            loan_amount = loan.loan_amount
            filter_ = dict(loan=loan)
            disbursement_id = loan.disbursement_id

        current_lender_balance = LenderBalanceCurrent.objects.select_for_update()\
                                                     .filter(lender=lender).last()

        if not current_lender_balance:
            logger.info({
                'method': 'updated_committed_amount_for_lender_balance',
                'msg': 'failed to update commmited current balance',
                'error': 'loan have invalid lender id: {}'.format(lender.id)
            })
            raise JuloException('Loan does not have lender id')

        loan_interest_amount = Payment.objects.filter(**filter_)\
                                              .aggregate(total_amount=Sum('installment_interest'))\
                                              .get('total_amount')

        updated_committed_amount = current_lender_balance.committed_amount - loan_amount

        updated_outstanding_interest_amount = current_lender_balance.outstanding_interest + \
            loan_interest_amount

        updated_outstanding_principal_amount = current_lender_balance.outstanding_principal + \
            loan_amount

        updated_dict = {
            'outstanding_principal': updated_outstanding_principal_amount,
            'outstanding_interest': updated_outstanding_interest_amount,
            'committed_amount': updated_committed_amount
        }

        calculate_available_balance.delay(
            current_lender_balance.id,
            SnapshotType.TRANSACTION,
            **updated_dict
        )

        filter = {'disbursement': disbursement_id}

        sepulsa_transaction = loan.sepulsatransaction_set.last()
        if sepulsa_transaction:
            filter = {'sepulsa_transaction': sepulsa_transaction}

        if loan.is_qris_product:
            filter = {'qris_transaction': loan.qris_transaction}

        juloshop_transaction = get_juloshop_transaction_by_loan(loan)
        if loan.is_ecommerce_product and juloshop_transaction:
            filter = {'juloshop_transaction': juloshop_transaction}

        lender_transaction_mapping = LenderTransactionMapping.objects.get_or_none(
            **filter
        )

        if lender_transaction_mapping is None:
            raise JuloException('Lender Transaction Mapping does not exists')

        transaction_type = LenderTransactionType.objects.get(
            transaction_type=LenderTransactionTypeConst.DISBURSEMENT
        )
        lender_transaction = LenderTransaction.objects.get_or_none(
            id=lender_transaction_mapping.lender_transaction_id)

        logger.info({
            'method': 'update_lender_balance_current_for_disbursement_async_task',
            'sepulsa_transaction': sepulsa_transaction,
            'loan': loan_id,
            'lender_transaction_id': lender_transaction,
            'disbursement_id': disbursement_id,
            'current_lender_balance': current_lender_balance,
            'msg': 'fetch lender data successfully'})
        if lender_transaction is None:
            lender_transaction = LenderTransaction.objects.create(
                lender=lender,
                lender_balance_current=current_lender_balance,
                transaction_type=transaction_type,
                transaction_amount=loan_amount * -1
            )
            logger.info({
                'method': 'update_lender_balance_current_for_disbursement_async_task',
                'lender': lender_transaction,
                'msg': 'create new lender successfully'})

        lender_transaction_mapping.update_safely(
            lender_transaction=lender_transaction
        )

        return current_lender_balance, lender_transaction


@task(queue="loan_normal")
def send_slack_notification_xendit_remaining_balance():
    setting_env = settings.ENVIRONMENT
    now = timezone.localtime(timezone.now())
    feature_setting=FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.NOTIFICATION_MINIMUM_XENDIT_BALANCE,
        is_active=True).first()
    if not feature_setting:
        return

    balance_threshold = feature_setting.parameters['balance_threshold']
    xendit_client = get_julo_xendit_client()
    response = xendit_client.get_balance()
    response_balance = response['balance']
    response_balance_idr = format_rupiahs(response_balance, 'no')
    should_send_message = False
    if setting_env != 'prod':
        message = "*(TESTING PURPOSE ONLY FROM %s)*\n" % (setting_env.upper())
    else:
        message = ""

    if response_balance < balance_threshold:
        should_send_message = True
        message += "Xendit balance is : {} please top up immediately \n".format(
            response_balance_idr
        )
        send_message_normal_format_to_users(message, feature_setting.parameters['users'])
    elif response_balance >= balance_threshold and now.minute < 10:
        should_send_message = True
        message += "xendit_balance: {} \n".format(
            response_balance_idr
        )

    if should_send_message is False:
        return

    header = "<!here>\n"
    formated_message = "{} ```{}```".format(header, message)
    send_message_normal_format(formated_message, channel='#partner_balance')


@task(queue="loan_high")
def regenerate_sphp_loan(loan_id):
    from juloserver.loan.services.agreement_related import get_julo_loan_agreement_template

    # This function can be used to generate sphp again
    try:
        loan = Loan.objects.get(pk=loan_id)
        body, _, _, _ = get_julo_loan_agreement_template(loan_id)
        if not body:
            logger.error({
                'action_view': 'regenerate_sphp',
                'data': {'loan_id': loan_id},
                'errors': "Template tidak ditemukan."
            })
            raise JuloException('SPHP template is not found.')

        now = datetime.now()
        application = loan.get_application
        filename = '{}_{}_{}_{}.pdf'.format(
            application.fullname,
            loan.loan_xid,
            now.strftime("%Y%m%d"),
            now.strftime("%H%M%S"))

        file_path = os.path.join(tempfile.gettempdir(), filename)

        # create local pdf file
        now = time.time()
        pdfkit.from_string(body, file_path)
        time_limit = 2
        elapsed = time.time() - now
        if elapsed > time_limit:
            logger.info({
                'action_view': 'regenerate_sphp',
                'data': {'loan_id': loan_id},
                'message': "PDF rendering takes {} seconds, which is more than the {} seconds limit.".format(elapsed, time_limit)
            })
            raise JuloException('Failed to create PDF')

        digital_signature = DigitalSignature(
            user=application.customer.user, key_name="key-{}-1".format(application.customer.user.id)
        )
        signature = digital_signature.sign(document=file_path)
        sphp_julo = Document.objects.create(
            document_source=loan.id,
            document_type='sphp_julo',
            filename=filename,
            loan_xid=loan.loan_xid,
            key_id=signature['key_id'],
            hash_digi_sign=signature['signature'],
            accepted_ts=signature['created_at'],
        )

        logger.info({
            'action_view': 'regenerate_sphp',
            'data': {'loan_id': loan_id, 'document_id': sphp_julo.id},
            'message': "success create PDF"
        })

        upload_document(sphp_julo.id, file_path, is_loan=True)

    except Exception as e:
        logger.exception({
            'action_view': 'regenerate_sphp',
            'data': {'loan_id': loan_id},
            'errors': str(e)
        })
        raise e


@task(queue="loan_high")
def reset_julo_one_loan_agreement(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        logger.warning({
            'action_view': 'reset_julo_one_loan_agreement',
            'data': {'loan_id': loan_id},
            'errors': "Loan tidak ditemukan."
        })
        return

    documents = Document.objects.filter(
        document_source=loan_id,
        document_type__in=('sphp_julo', 'skrtp_julo'),
        loan_xid=loan.loan_xid
    )
    if not documents:
        logger.warning({
            'action_view': 'reset_julo_one_loan_agreement',
            'data': {'loan_id': loan_id},
            'errors': "Dokumen tidak ditemukan."
        })
        return

    documents.update(document_type='old_loan_agreement')
    if LoanLenderHistory.objects.filter(loan=loan).count() > 0:
        generate_julo_one_loan_agreement(loan_id)


@task(queue="repayment_normal")
def pusdafil_process_lender_repayment_detail(year, month, day):
    pusdafil_feature = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.PUSDAFIL_LENDER_REPAYMENT_GDRIVE_PROCESS, is_active=True
    )
    if not pusdafil_feature:
        return

    pusdafil_folder_id = pusdafil_feature.parameters.get('folder_id')
    if not pusdafil_folder_id:
        return

    file_date = datetime.strptime("{}-{}-{}".format(year, month, day), "%Y-%m-%d")
    pusdafil_dataframe, date_folder_id, is_found = get_pusdafil_dataframe_from_gdrive(
        pusdafil_folder_id, year, month, day
    )

    if not is_found:
        return

    status = PusdafilLenderProcessStatusConst.SUCCESS
    error = None
    failed_rows = None
    try:
        failed_rows = process_lender_repayment_dataframe(pusdafil_dataframe)
    except Exception as err:
        # capture error all data
        status = PusdafilLenderProcessStatusConst.FAILED
        error = str(err)
        logger.error(
            {
                'action': "pusdafil_process_lender_repayment_detail",
                "date": "{}-{}-{}".format(year, month, day),
                'error': error,
            }
        )
        sentry_client.captureException()
        upload_pusdafil_error_to_gdrive(error, date_folder_id)

    if failed_rows and len(failed_rows) > 0:
        # capture error per row
        status = PusdafilLenderProcessStatusConst.PARTIAL_FAILED
        error = "Number of rows error: {}".format(len(failed_rows))
        upload_pusdafil_partial_error_to_gdrive(failed_rows, date_folder_id)

    LenderRepaymentDetailProcessLog.objects.update_or_create(
        file_date=file_date,
        defaults={'status': status, 'error_detail': error},
    )

    logger.info(
        {
            'action': "pusdafil_process_lender_repayment_detail",
            "date": "{}-{}-{}".format(year, month, day),
            'message': "finish process",
        }
    )

    return


@task(queue="repayment_normal")
def pusdafil_daily_process_lender_repayment_detail():
    # DAILY PROCESS FOR TODAY DATA
    today = timezone.localtime(timezone.now() - timedelta(days=1)).date()
    year = today.strftime("%Y")
    month = today.strftime("%m")
    day = today.strftime("%d")

    pusdafil_process_lender_repayment_detail.delay(year, month, day)

    return


@task(queue="repayment_normal")
def pusdafil_retry_process_lender_repayment_detail():
    # DAILY RETRY PROCESS FOR ALL FAILED DAYS
    failed_process = LenderRepaymentDetailProcessLog.objects.filter(
        status__in=[
            PusdafilLenderProcessStatusConst.FAILED,
            PusdafilLenderProcessStatusConst.PARTIAL_FAILED,
        ]
    )

    for process_log in failed_process.iterator():
        file_date = process_log.file_date
        year = file_date.strftime("%Y")
        month = file_date.strftime("%m")
        day = file_date.strftime("%d")

        pusdafil_process_lender_repayment_detail.delay(year, month, day)


@task(queue="repayment_normal")
def pusdafil_update_error_summary():
    pusdafil_feature = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.PUSDAFIL_LENDER_REPAYMENT_GDRIVE_PROCESS, is_active=True
    )
    if not pusdafil_feature:
        return

    pusdafil_folder_id = pusdafil_feature.parameters.get('folder_id')
    if not pusdafil_folder_id:
        return

    try:
        # REMOVE CURRENT SUMMARY FROM GDRIVE
        file_name = 'retry_error_summary.xlsx'
        delete_data_from_gdrive(file_name)

        # PROCESS NEW SUMMARY
        failed_process = LenderRepaymentDetailProcessLog.objects.filter(
            status__in=[
                PusdafilLenderProcessStatusConst.FAILED,
                PusdafilLenderProcessStatusConst.PARTIAL_FAILED,
            ]
        )

        error_row = []
        for process_log in failed_process.iterator():
            error_row.append([process_log.file_date, process_log.error_detail])

        # UPLOAD NEW SUMMARY TO GDRIVE
        error_df = pd.DataFrame(
            error_row,
            columns=['file_date', 'error_detail'],
        )
        upload_dataframe_to_gdrive(error_df, pusdafil_folder_id, file_name)
    except Exception as err:
        logger.error(
            {
                'action': "pusdafil_update_error_summary",
                'error': str(err),
            }
        )
        sentry_client.captureException()

    logger.info(
        {
            'action': "pusdafil_update_error_summary",
            'message': "success upload error summary to google drive",
        }
    )


def generate_qris_skrtp_julo(loan: Loan, agreement_type: str, filename: str, file_path: str):
    skrtp_julo = Document.objects.create(
        document_source=loan.id,
        document_type='%s_julo' % agreement_type,
        filename=filename,
        loan_xid=loan.loan_xid,
    )
    logger.info(
        {
            'action_view': 'generate_qris_skrtp_julo',
            'data': {
                'loan_id': loan.pk,
                'document_id': skrtp_julo.id,
                'agreement_type': agreement_type,
            },
            'message': "success create PDF",
        }
    )

    upload_document(skrtp_julo.id, file_path, is_loan=True)
    return skrtp_julo


@task(queue="regenerate_julo_one_loan_agreement_queue")
def regenerate_julo_one_loan_agreement_document_task(loan_ids: list):
    """
    Subtask to regenerate SKRTP documents, notify customers, and send emails.
    """
    for loan_id in loan_ids:
        generate_julo_one_loan_agreement(loan_id, is_new_generate=True)
        send_email_for_skrtp_regeneration.delay(loan_id)
        send_event_attributes_for_skrtp_regeneration.delay(loan_id)
