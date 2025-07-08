
from builtins import object
from collections import namedtuple


class PaymentServices(object):
    GOPAY = 'gopay'
    FASPAY = 'faspay'


class GoPayTransFraudStatus(object):
    '''
    accept : Approved by FDS.
    challenge: Questioned by FDS. NOTE: Approve transaction to accept
               it or transaction will auto cancel during settlement.
    deny: Denied by FDS. Transaction automatically failed
    '''
    ACCEPT = 'accept'
    CHALLENGE = 'challenge'
    DENY = 'deny'


class GoPayTransStatus(object):
    '''
    Transaction status after charge credit card transaction, the possible values are:
    1: capture - Transaction is accepted by the bank and ready for settlement.
    2: deny - transaction is denied by the bank or FDS.
    3: authorize - Credit card is authorized in pre-authorization feature
    '''
    CAPTURE = "capture"
    SETTLEMENT = "settlement"
    DENY = "deny"
    AUTHORIZE = "authorize" # Credit card is authorized in pre-authorization feature
    EXPIRE = "expire"
    PENDING = "pending"

    SUCCESS_STATUS = [CAPTURE, SETTLEMENT]

    @staticmethod
    def is_success(status, status_code, fraud_status=None):
        if not fraud_status:
            return (
                status in GoPayTransStatus.SUCCESS_STATUS and
                status_code == 200
            )
        return (
            status in GoPayTransStatus.SUCCESS_STATUS and
            fraud_status == GoPayTransFraudStatus.ACCEPT and
            status_code == 200
        )


class FasPayTransStatus(object):
    UNPROCESSED = 0
    IN_PROCESS = 1
    SUCCESS = 2
    FAILED = 3
    RESERVAL = 4
    BILL_NOT_FOUND = 5
    EXPIRED = 7
    PAYMENT_CANCELED = 8
    UNKNOWN = 9

    SUCCESS_STATUS = [SUCCESS]

    @staticmethod
    def is_success(status):
        return status == FasPayTransStatus.SUCCESS


PaybackTransStatusObj = namedtuple('PaybackTransStatusObj', 'STATUS DESCRIPTION')


class PaybackTransStatus(object):
    # transaction status
    PENDING = PaybackTransStatusObj(0, 'Pending')
    IN_PROCESS = PaybackTransStatusObj(1, 'In Process')
    SUCCESS = PaybackTransStatusObj(2, 'Success')
    FAILED = PaybackTransStatusObj(3, 'Failed')
    RESERVAL = PaybackTransStatusObj(4, 'Reserval')
    BILL_NOT_FOUND = PaybackTransStatusObj(5, 'Bill Not Found')
    EXPIRED = PaybackTransStatusObj(7, 'Expired')
    PAYMENT_CANCELED = PaybackTransStatusObj(8, 'Payment Canceled')
    UNKNOWN = PaybackTransStatusObj(9, 'Unknown')
    CREDIT_CARD_AUTHORIZE = PaybackTransStatusObj(10, 'Credit card authorize')


    STATUS_MAP = {
        PaymentServices.GOPAY: {
            GoPayTransStatus.CAPTURE: PENDING.STATUS,
            GoPayTransStatus.SETTLEMENT: SUCCESS.STATUS,
            GoPayTransStatus.DENY: FAILED.STATUS,
            GoPayTransStatus.AUTHORIZE: CREDIT_CARD_AUTHORIZE.STATUS,
            GoPayTransStatus.EXPIRE: EXPIRED.STATUS,
            GoPayTransStatus.PENDING: PENDING.STATUS
        },
        PaymentServices.FASPAY: {
            FasPayTransStatus.UNPROCESSED: PENDING.STATUS,
            FasPayTransStatus.IN_PROCESS: IN_PROCESS.STATUS,
            FasPayTransStatus.SUCCESS: SUCCESS.STATUS,
            FasPayTransStatus.FAILED: FAILED.STATUS,
            FasPayTransStatus.RESERVAL: RESERVAL.STATUS,
            FasPayTransStatus.BILL_NOT_FOUND: BILL_NOT_FOUND.STATUS,
            FasPayTransStatus.EXPIRED: EXPIRED.STATUS,
            FasPayTransStatus.PAYMENT_CANCELED: PAYMENT_CANCELED.STATUS,
            FasPayTransStatus.UNKNOWN: UNKNOWN.STATUS,
        }
    }

    DESCRIPTION_MAP = {
        PENDING.STATUS: PENDING.DESCRIPTION,
        IN_PROCESS.STATUS: IN_PROCESS.DESCRIPTION,
        SUCCESS.STATUS: SUCCESS.DESCRIPTION,
        FAILED.STATUS: FAILED.DESCRIPTION,
        RESERVAL.STATUS: RESERVAL.DESCRIPTION,
        BILL_NOT_FOUND.STATUS: BILL_NOT_FOUND.DESCRIPTION,
        EXPIRED.STATUS: EXPIRED.DESCRIPTION,
        PAYMENT_CANCELED.STATUS: PAYMENT_CANCELED.DESCRIPTION,
        UNKNOWN.STATUS: UNKNOWN.DESCRIPTION,
        CREDIT_CARD_AUTHORIZE.STATUS: CREDIT_CARD_AUTHORIZE.DESCRIPTION
    }


    @staticmethod
    def get_mapped_description(inbo_status):
        try:
            return PaybackTransStatus.DESCRIPTION_MAP[inbo_status]
        except:
            return ""


    @staticmethod
    def get_mapped_status(payment_service, inbo_status):
        return PaybackTransStatus.STATUS_MAP[payment_service][inbo_status]


    @staticmethod
    def is_transaction_success(req_data):
        result = False
        payment_service = req_data.get('payment_service')
        inbo_status = req_data.get('inbo_status')
        fraud_status = req_data.get('fraud_status')
        if payment_service:
            if payment_service == PaymentServices.GOPAY:
                result = GoPayTransStatus.is_success(inbo_status, fraud_status)
            elif payment_service == PaymentServices.FASPAY:
                result = FasPayTransStatus.is_success(inbo_status)
        return result