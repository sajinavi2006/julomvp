import logging
from typing import List, Dict, Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from bulk_update.helper import bulk_update

from juloserver.channeling_loan.constants.fama_constant import FAMADPDRejectionStatusEligibility
from juloserver.channeling_loan.models import (
    ChannelingEligibilityStatusHistory,
    ChannelingEligibilityStatus,
    ChannelingLoanApprovalFile,
    FAMAChannelingRepaymentApproval,
)
from juloserver.channeling_loan.exceptions import (
    ChannelingLoanApprovalFileDocumentNotFound,
    ChannelingLoanApprovalFileLoanXIDNotFound,
)
from juloserver.channeling_loan.utils import parse_numbers_only
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import RedisLockKeyName
from juloserver.julo.context_managers import redis_lock_for_update
from juloserver.julo.services import update_lender_disbursement_counter
from juloserver.followthemoney.models import LenderTransactionType
from juloserver.followthemoney.constants import LenderTransactionTypeConst

from juloserver.channeling_loan.constants import (
    ChannelingStatusConst,
    ChannelingConst,
    ChannelingActionTypeConst,
    FAMAChannelingConst,
)
from juloserver.julo.models import Loan, Document
from juloserver.channeling_loan.services.general_services import (
    update_loan_lender,
    calculate_old_lender_balance,
    calculate_new_lender_balance,
    send_notification_to_slack,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def reassign_lender_fama_rejected_loans(approval_data):
    from juloserver.loan.services.lender_related import julo_one_get_fama_buyback_lender

    reassigned_loans = list()
    action = "channeling_loan.services.fama_services.reassign_lender_fama_rejected_loans"

    base_logger_data = {
        "action": action,
        "approval_data": approval_data,
    }

    logger.info({"message": "Start reassign lender from FAMA rejected loans", **base_logger_data})

    all_rejected_loan_ids = []

    for approval in approval_data:
        all_rejected_loan_ids += approval['rejected_loan_ids']

    if not all_rejected_loan_ids:
        logger.info({"message": "No FAMA rejected loans found", **base_logger_data})
        return

    loans = Loan.objects.filter(id__in=all_rejected_loan_ids).select_related("lender")

    with transaction.atomic():
        for loan in loans:
            assigned_lender = julo_one_get_fama_buyback_lender(loan)

            if not assigned_lender:
                logger.info(
                    {
                        "message": "Unable to reassign lender since no lender available",
                        "loan_id": loan.id,
                        "current_lender": loan.lender.lender_name,
                        **base_logger_data,
                    }
                )
                continue

            old_lender, channeling_loan_history = update_loan_lender(
                loan,
                assigned_lender,
                ChannelingConst.FAMA,
                "Reassign FAMA rejected loan",
                is_channeling=True,
            )

            if old_lender.is_pre_fund_channeling_flow:
                amount = loan.loan_amount
                transaction_type = LenderTransactionType.objects.get_or_none(
                    transaction_type=LenderTransactionTypeConst.CHANNELING_PREFUND_REJECT
                )

                # Bring amount back to old lender
                calculate_old_lender_balance(
                    loan.id, amount, old_lender, channeling_loan_history, transaction_type
                )

                # Deduct target lender balance
                calculate_new_lender_balance(
                    loan.id, amount, assigned_lender, channeling_loan_history, transaction_type
                )

            loan.udate = timezone.localtime(timezone.now())
            loan.lender_id = assigned_lender.pk
            loan.partner_id = assigned_lender.user.partner.pk

            update_lender_disbursement_counter(assigned_lender)

            reassigned_loans.append(loan)

        bulk_update(reassigned_loans, update_fields=["udate", "lender_id", "partner_id"])

    logger.info(
        {
            "message": "Finish reassign lender from FAMA rejected loans",
            "all_rejected_loan_ids": str(all_rejected_loan_ids),
            "reassigned_loans_ids": str(reassigned_loans),
            **base_logger_data,
        }
    )


def update_fama_eligibility_rejected_by_dpd(loan: Loan):
    get_eligibility_status = ChannelingEligibilityStatus.objects.filter(
        channeling_type=ChannelingConst.FAMA,
        application=loan.get_application,
    )
    if get_eligibility_status:
        get_eligibility_status.update(
            eligibility_status=ChannelingStatusConst.INELIGIBLE,
            reason=FAMADPDRejectionStatusEligibility.reason,
            version=FAMADPDRejectionStatusEligibility.new_version,
        )
        ChannelingEligibilityStatusHistory.objects.create(
            application=loan.get_application,
            channeling_type=ChannelingConst.FAMA,
            eligibility_status=ChannelingStatusConst.INELIGIBLE,
            version=FAMADPDRejectionStatusEligibility.new_version,
        )
    return


class FAMARepaymentApprovalServices:
    @staticmethod
    def parse_data_from_txt_content(txt_content: str) -> List[Dict[str, Any]]:
        """
        :param txt_content: here is an example
        Line 0: JTF|JULO|20250414|6156|2157479087.00
        Line 1: JTF1007264431|LCJTF2025021400016|IDR|LTP|20250410|20250414|1744287870055418|
        13000.00|61872.00|74872.00|74872.00|0.00|2|0.00|0.00|0.00|Posted Successfully
        Line 2: JTF1039222507|LCJTF2025022800011|IDR|PYM|20250411|20250414|1744287870055419|
        333063.00|1237201.00|1570264.00|1570264.00|0.00|2|0.00|0.00|0.00|Rejected : reason...,
        :return: List of dictionaries containing parsed data
        """
        lines = txt_content.splitlines()
        if not lines:
            return []

        lines.pop(0)  # remove header line

        records = []
        try:
            for line in lines:
                if not line:
                    # skip empty lines (if any, it usually at the end of the file)
                    continue

                fields = line.split('|')
                records.append(
                    {
                        'loan_xid': int(parse_numbers_only(fields[0])),
                        'account_id': fields[0],
                        'account_no': fields[1],
                        'country_currency': fields[2],
                        'payment_type': fields[3],
                        'payment_date': fields[4],
                        'posting_date': fields[5],
                        'partner_payment_id': fields[6],
                        'interest_amount': int(float(fields[7])),
                        'principal_amount': int(float(fields[8])),
                        'installment_amount': int(float(fields[9])),
                        'payment_amount': int(float(fields[10])),
                        'over_payment': int(float(fields[11])),
                        'term_payment': fields[12],
                        'late_charge_amount': int(float(fields[13])),
                        'early_payment_fee': int(float(fields[14])),
                        'annual_fee_amount': int(float(fields[15])),
                        'status': fields[16],
                    }
                )
        except (IndexError, ValueError) as e:
            raise e

        return records

    @staticmethod
    def validate_loans_exist_and_get_mapping(records: List[Dict[str, Any]]) -> Dict[str, Loan]:
        """Validate all loan XIDs exist and return loan mapping"""
        unique_loan_xids = set([record['loan_xid'] for record in records])
        loans = Loan.objects.filter(loan_xid__in=unique_loan_xids).all()

        if len(loans) != len(unique_loan_xids):
            raise ChannelingLoanApprovalFileLoanXIDNotFound('Some loan XIDs not found')

        return {loan.loan_xid: loan for loan in loans}

    @staticmethod
    def create_approval_objects(
        records: List[Dict[str, Any]],
        loan_mapping: Dict[str, Loan],
        channeling_loan_approval_file_id: int,
    ) -> List[FAMAChannelingRepaymentApproval]:
        return [
            FAMAChannelingRepaymentApproval(
                channeling_loan_approval_file_id=channeling_loan_approval_file_id,
                loan_id=loan_mapping[record['loan_xid']].id,
                account_id=record['account_id'],
                account_no=record['account_no'],
                country_currency=record['country_currency'],
                payment_type=record['payment_type'],
                payment_date=record['payment_date'],
                posting_date=record['posting_date'],
                partner_payment_id=record['partner_payment_id'],
                interest_amount=record['interest_amount'],
                principal_amount=record['principal_amount'],
                installment_amount=record['installment_amount'],
                payment_amount=record['payment_amount'],
                over_payment=record['over_payment'],
                term_payment=record['term_payment'],
                late_charge_amount=record['late_charge_amount'],
                early_payment_fee=record['early_payment_fee'],
                annual_fee_amount=record['annual_fee_amount'],
                status=record['status'],
            )
            for record in records
        ]

    @staticmethod
    def is_processed_file(filename: str) -> bool:
        recent_approval_repayment = ChannelingLoanApprovalFile.objects.filter(
            channeling_type=ChannelingConst.FAMA,
            file_type=ChannelingActionTypeConst.REPAYMENT,
            is_processed=True,
            is_uploaded=True,
        ).last()
        if recent_approval_repayment:
            recent_document = Document.objects.get_or_none(id=recent_approval_repayment.document_id)
            if not recent_document:
                raise ChannelingLoanApprovalFileDocumentNotFound(
                    'document_id={} not found'.format(recent_approval_repayment.document_id)
                )

            recent_filename = recent_document.filename

            if recent_filename == filename:
                return True

        return False

    @staticmethod
    def handle_processed_file(approval_file: ChannelingLoanApprovalFile, filename: str) -> bool:
        """Handle the case when the current file was already processed"""
        today = timezone.now().date().strftime(FAMAChannelingConst.FILENAME_DATE_FORMAT)

        # If the current filename matches with previous successful, but contains today
        # -> data was updated before (maybe from manual clicking button in CRM)
        # => no need to process the file again because already uploaded
        if today in filename:
            approval_file.is_uploaded = True
            approval_file.save()
            return True
        return False

    def process_approval_file(
        self, approval_file: ChannelingLoanApprovalFile, txt_content: str
    ) -> List[FAMAChannelingRepaymentApproval]:
        records = self.parse_data_from_txt_content(txt_content=txt_content)
        if not records:
            return []

        return self.create_approval_objects(
            records=records,
            loan_mapping=self.validate_loans_exist_and_get_mapping(records=records),
            channeling_loan_approval_file_id=approval_file.id,
        )

    @staticmethod
    def send_success_store_slack_notification(filename: str, num_records: int) -> None:
        """Send Slack notification about successful processing"""
        message = (
            f"FAMA Repayment file processed: {filename}. "
            f"{num_records} successful repayments stored."
        )
        send_notification_to_slack(
            slack_messages=message, slack_channel=settings.FAMA_SLACK_NOTIFICATION_CHANNEL
        )

    @transaction.atomic
    def store_data_and_notify_slack(
        self, approval_file_id: int, filename: str, txt_content: str
    ) -> bool:
        with redis_lock_for_update(
            key_name=RedisLockKeyName.STORE_FAMA_REPAYMENT_APPROVAL_DATA, unique_value=filename
        ):
            approval_file = ChannelingLoanApprovalFile.objects.get_or_none(id=approval_file_id)

            if self.is_processed_file(filename=filename):
                return self.handle_processed_file(approval_file, filename)

            approvals = self.process_approval_file(approval_file, txt_content)
            if approvals:
                FAMAChannelingRepaymentApproval.objects.bulk_create(
                    objs=approvals, batch_size=FAMAChannelingConst.BATCH_SIZE
                )

            approval_file.is_uploaded = True
            approval_file.save()

            self.send_success_store_slack_notification(
                filename=filename, num_records=len(approvals)
            )

            return True

    @staticmethod
    def send_exceed_max_retry_slack_notification() -> None:
        message = "FAMA Repayment file processing exceeded max retry times, need to check with FAMA"
        send_notification_to_slack(
            slack_messages=message, slack_channel=settings.FAMA_SLACK_NOTIFICATION_CHANNEL
        )
