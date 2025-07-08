class PaymentDepositStatus:
    PENDING = 'PENDING'
    PARTIAL = 'PARTIAL'
    SUCCESS = 'SUCCESS'
    EXPIRED = 'EXPIRED'

    @classmethod
    def waiting(cls):
        return [cls.PENDING, cls.PARTIAL]

    @classmethod
    def has_paid(cls):
        return [cls.SUCCESS, cls.PARTIAL]
