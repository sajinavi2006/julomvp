from builtins import object
class PaylaterConst(object):
    PARTNER_NAME='bukalapak_paylater'
    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_PAID_OFF = 'paid off'
    SUB_FEE = 0
    INTEREST_RATE = 0
    ADMIN_FEE = 0
    LIMIT = 3000000

    BINARY_CHECK = (
        'application_date_of_birth',
        'has_active_loan',
        'good_payment_history',
        'customer_window_transaction',
        'customer_minimum_transaction'
        )

class LineTransactionType(object):
    TYPE_INVOICE = {'name': 'invoice', 'type': 'debit'}
    TYPE_REFUND = {'name': 'refund', 'type': 'credit'}
    TYPE_REFUND_PAID = {'name': 'refund_paid', 'type': 'credit'}
    TYPE_CANCEL_PAYMENT = {'name': 'cancel_payment', 'type': 'credit'}
    TYPE_PAYMENT = {'name': 'payment', 'type': 'credit'}
    TYPE_LATEFEE = {'name': 'late_fee', 'type': 'debit'}
    TYPE_LATEFEE_VOID = {'name': 'late_fee_void', 'type': 'credit'}
    TYPE_WAIVE_LATEFEE = {'name': 'waive_late_fee', 'type': 'credit'}
    TYPE_WAIVE_LATEFEE_VOID = {'name': 'waive_late_fee_void', 'type': 'debit'}

    @classmethod
    def is_hide(cls):
        return [
            cls.TYPE_PAYMENT['name'],
            cls.TYPE_LATEFEE['name'],
            cls.TYPE_LATEFEE_VOID['name'],
            cls.TYPE_WAIVE_LATEFEE['name'],
            cls.TYPE_WAIVE_LATEFEE_VOID['name']
        ]

class PaylaterCreditMatrix(object):
    #update this when threshold done from DE
    A_THRESHOLD = 0.90
    MVP_CLUSTER = 'MVP'
    POTENTIAL_MVP_CLUSTER = 'Potential MVP'
    CHURNED_CLUSTER = 'Churned'
    OPPORTUNISTIC_CLUSTER = 'Opportunistic'

class StatementEventConst(object):
    WAIVE_LATE_FEE = 'waive_late_fee'
    WAIVE_LATE_FEE_GROUP_1 = 'waive_late_fee_group_1'
    WAIVE_SUBSCRIPTION_FEE = 'waive_subscription_fee'
    WAIVE_LATE_FEE_GROUP_2 = 'waive_late_fee_group_2'
