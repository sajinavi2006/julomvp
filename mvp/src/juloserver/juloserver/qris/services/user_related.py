import logging
from typing import Tuple, List
from dateutil.relativedelta import relativedelta
from collections import defaultdict
from django.db import transaction
from django.utils import timezone
from juloserver.julo.models import (
    Image,
    Partner,
    Customer,
    MasterAgreementTemplate,
    Application,
)
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.qris.serializers import UploadImageSerializer
from juloserver.qris.models import (
    QrisLinkageLenderAgreement,
    QrisUserState,
    QrisPartnerLinkage,
    QrisPartnerTransaction,
)
from juloserver.qris.services.core_services import is_qris_linkage_signed_with_lender
from juloserver.qris.services.linkage_related import get_or_create_linkage
from juloserver.qris.tasks import upload_qris_signature_and_master_agreement_task
from juloserver.qris.constants import (
    QrisLinkageStatus,
    QrisTransactionStatus,
    LIMIT_QRIS_TRANSACTION_MONTHS,
    HASH_DIGI_SIGN_FORMAT,
    QrisFeDisplayedStatus,
    QrisTransactionStatusColor,
    QrisStatusImageLinks,
)
from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.followthemoney.models import LenderCurrent, LoanAgreementTemplate
from juloserver.followthemoney.constants import MasterAgreementTemplateName, LenderName
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.portal.object.loan_app.constants import ImageUploadType
from babel.dates import format_date
from django.template.loader import render_to_string
from django.template import Context, Template
from juloserver.julo.utils import (
    display_rupiah,
    display_rupiah_skrtp,
    display_rupiah_no_space,
)
from juloserver.qris.exceptions import AlreadySignedWithLender, QrisLinkageNotFound
from juloserver.julo.models import Loan

logger = logging.getLogger(__name__)


class QrisAgreementService:
    def __init__(self, customer: Customer, lender: LenderCurrent):
        self.customer = customer
        self.lender = lender

    def validate_agreement_type(self, partner_name: str, document_type: str) -> Tuple[bool, str]:
        if partner_name not in PartnerNameConstant.qris_partners():
            return False, "Product not supported"
        if document_type not in LoanAgreementType.QRIS_DOCUMENT_TYPES:
            return False, "Document type not supported"

        return True, None

    def get_document_content(self, agreement_type: str) -> str:
        if agreement_type == LoanAgreementType.MASTER_AGREEMENT:
            return self._get_master_agreement_content()
        return None

    def _get_master_agreement_content(self) -> str:
        application = self.customer.account.get_active_application()
        return get_master_agreement_html(application, lender=self.lender)


def create_signature_image(
    image_type: str, image_source_id: int, input_data: UploadImageSerializer
) -> int:
    """
    Create the signature Image
    ::param image_type: str
    ::param image_source_id: int (user_state_id, application_id, etc)
    ::param input_data: UploadImageSerializer
    """
    logger.info(
        {
            "action": "qris.services.user_related.create_signature_image",
            "image_type": image_type,
            "image_source_id": image_source_id,
            "input_data": input_data,
        }
    )
    signature_image = Image(
        image_source=image_source_id,
        image_type=image_type,
    )
    signature_image.save()

    signature_image.image.save(
        name=input_data['data'],
        content=input_data['upload'],
    )
    return signature_image.id


class QrisUploadSignatureService:
    def __init__(
        self,
        customer: Customer,
        signature_image_data: UploadImageSerializer,
        partner: Partner,
        lender: LenderCurrent,
    ):
        self.customer = customer
        self.signature_image_data = signature_image_data
        self.partner = partner
        self.lender = lender
        self.image_id = None

    def process_linkage_and_upload_signature(self) -> None:
        """
        In transaction:
        - Get or Create Linkage & UserState
        - Create Signature Image Object
        - Create Qris Lender Agreement
        - Trigger async task to upload signature & create doc

        User can sign many times (because of multiple lenders) per partner
        """
        with transaction.atomic():
            linkage, _ = get_or_create_linkage(
                customer_id=self.customer.id,
                partner_id=self.partner.id,
            )

            is_already_signed = is_qris_linkage_signed_with_lender(
                linkage_id=linkage.id,
                lender_id=self.lender.id,
            )

            if is_already_signed:
                logger.info(
                    {
                        "action": "QrisUploadSignatureService._create_data_for_uploading_qris_signature",
                        "message": f"Qris Linkage already signed with lender: {self.lender.lender_name}",
                        "customer_id": self.customer.id,
                        "partner": self.partner.name,
                    }
                )
                # raise to rollback transaction
                raise AlreadySignedWithLender("Qris Linkage already signed with lender")

            user_state, is_user_state_created = self._get_or_create_user_state(linkage=linkage)

            self.image_id = create_signature_image(
                image_type=ImageUploadType.QRIS_SIGNATURE,
                image_source_id=linkage.id,  # previous was user state id
                input_data=self.signature_image_data,
            )

            # only update user_state.signature_image_id for first time (for data consistency)
            # others will be found in QrisLinkageLenderAgreement
            if is_user_state_created:
                user_state.signature_image_id = self.image_id
                user_state.save(update_fields=['signature_image_id'])

            qris_lender_agreement = self.create_qris_lender_agreement(
                linkage=linkage, signature_image_id=self.image_id
            )

            self._upload_signature_and_create_master_agreement(
                qris_lender_agreement_id=qris_lender_agreement.id,
            )

    def create_qris_lender_agreement(self, linkage: QrisPartnerLinkage, signature_image_id: int):
        return QrisLinkageLenderAgreement.objects.create(
            qris_partner_linkage=linkage,
            lender_id=self.lender.id,
            signature_image_id=signature_image_id,
        )

    def _get_or_create_user_state(self, linkage: QrisPartnerLinkage):
        return QrisUserState.objects.get_or_create(
            qris_partner_linkage_id=linkage.pk,
        )

    def _upload_signature_and_create_master_agreement(self, qris_lender_agreement_id: int) -> None:
        execute_after_transaction_safely(
            lambda: upload_qris_signature_and_master_agreement_task.delay(
                qris_lender_agreement_id=qris_lender_agreement_id,
            )
        )


def get_master_agreement_html(
    application: Application, lender: LenderCurrent, signature_image: Image = None
) -> str:
    hash_digi_sign = HASH_DIGI_SIGN_FORMAT.format(str(application.application_xid))
    context = {
        "hash_digi_sign": hash_digi_sign,
        "signed_date": format_date(
            timezone.localtime(timezone.now()).date(), 'd MMMM yyyy', locale='id_ID'
        ),
        "application": application,
        "dob": format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        "lender": lender,
        "qris_signature": "",
    }

    if signature_image:
        context["qris_signature"] = signature_image.thumbnail_url_api

    template = MasterAgreementTemplate.objects.filter(
        product_name=MasterAgreementTemplateName.QRIS_J1, is_active=True
    ).first()
    if template:
        return Template(template.parameters).render(Context(context))

    return render_to_string('loan_agreement/qris_master_agreement.html', context=context)


class QrisListTransactionService:
    def __init__(self, customer_id: int, partner_id: int):
        self.customer_id = customer_id
        self.partner_id = partner_id

    def _get_qris_partner_linkage(self) -> QrisPartnerLinkage:
        return QrisPartnerLinkage.objects.filter(
            customer_id=self.customer_id,
            status=QrisLinkageStatus.SUCCESS,
            partner_id=self.partner_id,
        ).first()

    def _get_qris_partner_transactions(
        self, qris_user_linkage: QrisPartnerLinkage, limit: int = None
    ) -> List[QrisPartnerTransaction]:
        """Only get transaction success in 6 months"""
        today = timezone.localtime(timezone.now()).date() - relativedelta(
            months=LIMIT_QRIS_TRANSACTION_MONTHS
        )
        transactions_queryset = (
            qris_user_linkage.transactions.filter(
                status=QrisTransactionStatus.SUCCESS, cdate__date__gte=today
            )
            .values('pk', 'total_amount', 'merchant_name', 'cdate')
            .order_by('-pk')
        )

        if limit:
            transactions_queryset = transactions_queryset[:limit]

        return list(transactions_queryset)

    def _get_recent_qris_partner_transactions(
        self, qris_user_linkage: QrisPartnerLinkage, limit: int = None
    ) -> List[QrisPartnerTransaction]:
        """Only get transactions in 6 months"""
        starting_date_cutoff = timezone.localtime(timezone.now()).date() - relativedelta(
            months=LIMIT_QRIS_TRANSACTION_MONTHS
        )
        transactions_queryset = (
            qris_user_linkage.transactions.filter(
                status__in=QrisTransactionStatus.get_statuses_for_transaction_history(),
                cdate__date__gte=starting_date_cutoff
            )
            .values('pk', 'total_amount', 'merchant_name', 'cdate', 'status', 'loan_id')
            .order_by('-pk')
        )

        if limit:
            transactions_queryset = transactions_queryset[:limit]

        return list(transactions_queryset)

    def get_successful_transaction(self, limit: int = None) -> List[QrisPartnerTransaction]:
        qris_user_linkage = self._get_qris_partner_linkage()
        if not qris_user_linkage:
            raise QrisLinkageNotFound

        transactions = self._get_qris_partner_transactions(qris_user_linkage, limit)
        if not transactions:
            return []

        formatted_data = defaultdict(list)
        for transaction in transactions:
            month_year = transaction['cdate'].strftime('%m-%Y')
            formatted_data[month_year].append(
                {
                    "merchant_name": transaction['merchant_name'],
                    "transaction_date": transaction['cdate'].strftime('%d-%m-%Y'),
                    "amount": display_rupiah(transaction['total_amount']),
                }
            )

        response_data = []
        for date, transactions in formatted_data.items():
            response_data.append({"date": date, "transactions": transactions})
        return response_data

    def _get_status_details(self, status):
        status_mapping = {
            QrisTransactionStatus.PENDING: {
                "qris_transaction_status": QrisFeDisplayedStatus.PENDING,
                "transaction_status_color": QrisTransactionStatusColor.YELLOW,
                "status_image_link": QrisStatusImageLinks.PENDING,
            },
            QrisTransactionStatus.SUCCESS: {
                "qris_transaction_status": QrisFeDisplayedStatus.SUCCESS,
                "transaction_status_color": QrisTransactionStatusColor.GREEN,
                "status_image_link": QrisStatusImageLinks.SUCCESS,
            },
            QrisTransactionStatus.FAILED: {
                "qris_transaction_status": QrisFeDisplayedStatus.FAILED,
                "transaction_status_color": QrisTransactionStatusColor.RED,
                "status_image_link": QrisStatusImageLinks.FAILED,
            },
        }
        return status_mapping.get(status.lower())

    def _displayed_amount(self, transaction):
        """
        Returns the formatted transaction amount with a '-' prefix
        if the transaction is not FAILED.
        """
        amount = display_rupiah_no_space(transaction['total_amount'])
        if transaction['status'].lower() != QrisTransactionStatus.FAILED:
            amount = "-" + amount
        return amount

    def get_all_transactions(self, limit: int = None) -> List[QrisPartnerTransaction]:
        qris_user_linkage = self._get_qris_partner_linkage()
        if not qris_user_linkage:
            raise QrisLinkageNotFound

        transactions = self._get_recent_qris_partner_transactions(qris_user_linkage, limit)
        if not transactions:
            return []

        formatted_data = defaultdict(list)
        for transaction in transactions:
            status_details = self._get_status_details(transaction['status'])
            month_year = transaction['cdate'].strftime('%m-%Y')
            loan = Loan.objects.get_or_none(id=transaction['loan_id'])
            formatted_data[month_year].append(
                {
                    "merchant_name": transaction['merchant_name'],
                    "transaction_date": transaction['cdate'].strftime('%d-%m-%Y'),
                    "amount": self._displayed_amount(transaction),
                    "loan_xid": loan.loan_xid,
                    **status_details,
                }
            )

        response_data = []
        for date, transactions in formatted_data.items():
            response_data.append({"date": date, "transactions": transactions})
        return response_data


def get_qris_skrtp_agreement_html(
    loan: Loan,
    application: Application,
) -> str:
    hash_digi_sign = HASH_DIGI_SIGN_FORMAT.format(str(application.application_xid))
    qris_transaction = QrisPartnerTransaction.objects.get(loan_id=loan.id)
    qris_partner_state = QrisUserState.objects.get(
        qris_partner_linkage_id=qris_transaction.qris_partner_linkage_id
    )
    signature_image = qris_partner_state.signature_image
    transaction_date = loan.fund_transfer_ts if loan.fund_transfer_ts else loan.cdate

    # adjust payment due date and amount
    payments = loan.payment_set.all().order_by('payment_number')
    for payment in payments:
        payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
        payment.due_amount = display_rupiah_skrtp(payment.due_amount + payment.paid_amount)

    context = {
        "application": application,
        "dob": format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        "lender": loan.lender,
        "qris_signature": signature_image.thumbnail_url_api,
        "hash_digi_sign": hash_digi_sign,
        "signed_date": format_date(
            timezone.localtime(signature_image.cdate).date(), 'd MMMM yyyy', locale='id_ID'
        ),
        "payments": payments,
        "loan_xid": loan.loan_xid,
        "transaction_date": format_date(
            timezone.localtime(transaction_date).date(), 'd MMMM yyyy', locale='id_ID'
        ),
    }

    template = LoanAgreementTemplate.objects.get_or_none(
        lender=loan.lender, is_active=True, agreement_type=LoanAgreementType.QRIS_SKRTP
    )

    if not template:
        template = LoanAgreementTemplate.objects.get_or_none(
            lender=None, is_active=True, agreement_type=LoanAgreementType.QRIS_SKRTP
        )

    if not template:
        return render_to_string('loan_agreement/qris_skrtp.html', context=context)

    return Template(template.body).render(Context(context))
