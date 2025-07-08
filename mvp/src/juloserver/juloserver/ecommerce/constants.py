from builtins import object

from juloserver.julo.statuses import LoanStatusCodes

ORDER_TIMEOUT_SECONDS = 60


class EcommerceConstant(object):
    BUKALAPAK = 'Bukalapak'
    TOKOPEDIA = 'Tokopedia'
    SHOPEE = 'Shopee'
    BLIBLI = 'Blibli'
    LAZADA = 'Lazada'
    IPRICE = 'iPrice'
    JULOSHOP = 'Julo Shop'

    WARNING_MESSAGE_TEXT = 'Bayar E-commerce hanya bisa dilakukan dengan Nomor Virtual'\
                           ' Account dari Bank tertentu'
    JULOSHOP_REDIRECT_URL = "julo://e-commerce/juloshop/checkout-redirect?transaction_id={}"
    JULOSHOP_MAX_ITEMS_CHECKOUT = 1

    @classmethod
    def get_all_ecommerce(self):
        return [self.BUKALAPAK, self.TOKOPEDIA, self.SHOPEE, self.LAZADA, self.BLIBLI]


class CategoryType:
    MARKET = 'marketplace'
    ECOMMERCE = 'e-commerce'


class IpriceTransactionStatus:
    DRAFT = 'draft'
    PROCESSING = 'processing'
    LOAN_APPROVED = 'loan_approved'
    LOAN_REJECTED = 'loan_rejected'
    REFUNDED = 'refunded'

    @staticmethod
    def by_loan_status(loan_status):
        mapping = {
            LoanStatusCodes.DRAFT: IpriceTransactionStatus.DRAFT,
            LoanStatusCodes.INACTIVE: IpriceTransactionStatus.DRAFT,
            LoanStatusCodes.LENDER_APPROVAL: IpriceTransactionStatus.PROCESSING,
            LoanStatusCodes.LENDER_REJECT: IpriceTransactionStatus.LOAN_REJECTED,
            LoanStatusCodes.FUND_DISBURSAL_ONGOING: IpriceTransactionStatus.PROCESSING,
            LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING: IpriceTransactionStatus.PROCESSING,
            LoanStatusCodes.CANCELLED_BY_CUSTOMER: IpriceTransactionStatus.LOAN_REJECTED,
            LoanStatusCodes.SPHP_EXPIRED: IpriceTransactionStatus.LOAN_REJECTED,
            LoanStatusCodes.FUND_DISBURSAL_FAILED: IpriceTransactionStatus.PROCESSING,
            LoanStatusCodes.CURRENT: IpriceTransactionStatus.LOAN_APPROVED,
            LoanStatusCodes.LOAN_1DPD: IpriceTransactionStatus.LOAN_APPROVED,
            LoanStatusCodes.LOAN_5DPD: IpriceTransactionStatus.LOAN_APPROVED,
            LoanStatusCodes.LOAN_30DPD: IpriceTransactionStatus.LOAN_APPROVED,
            LoanStatusCodes.LOAN_60DPD: IpriceTransactionStatus.LOAN_APPROVED,
            LoanStatusCodes.LOAN_90DPD: IpriceTransactionStatus.LOAN_APPROVED,
            LoanStatusCodes.LOAN_120DPD: IpriceTransactionStatus.LOAN_APPROVED,
            LoanStatusCodes.LOAN_150DPD: IpriceTransactionStatus.LOAN_APPROVED,
            LoanStatusCodes.LOAN_180DPD: IpriceTransactionStatus.LOAN_APPROVED,
            LoanStatusCodes.RENEGOTIATED: IpriceTransactionStatus.LOAN_APPROVED,
            LoanStatusCodes.PAID_OFF: IpriceTransactionStatus.LOAN_APPROVED,
            LoanStatusCodes.SELL_OFF: IpriceTransactionStatus.LOAN_APPROVED,
            LoanStatusCodes.TRANSACTION_FAILED: IpriceTransactionStatus.LOAN_REJECTED,
            LoanStatusCodes.GRAB_AUTH_FAILED: IpriceTransactionStatus.LOAN_REJECTED,
        }
        transaction_status = mapping.get(loan_status)
        if transaction_status is None:
            raise ValueError('No iPrice transaction status for loan status: {}'.format(loan_status))

        return transaction_status


class JuloShopTransactionStatus:
    DRAFT = 'draft'
    PROCESSING = 'processing'
    SUCCESS = 'success'
    FAILED = 'failed'

    @classmethod
    def all(cls):
        return [cls.DRAFT, cls.PROCESSING, cls.SUCCESS, cls.FAILED]

    @classmethod
    def status_changeable(cls):
        return [
            (cls.DRAFT, cls.FAILED),
            (cls.DRAFT, cls.PROCESSING),
            (cls.PROCESSING, cls.SUCCESS),
            (cls.PROCESSING, cls.FAILED)
        ]
