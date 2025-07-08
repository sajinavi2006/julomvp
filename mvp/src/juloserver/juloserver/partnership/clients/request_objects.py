from builtins import object
import json


class PlainObject(object):
    def __init__(self):
        pass

    def to_json(self):
        return json.dumps(self.to_dict())

    def to_dict(self):
        return json.loads(json.dumps(
            self, default=lambda o: o.__dict__ if hasattr(o, "__dict__") else o.__str__()))


class RefreshObject(PlainObject):
    accessToken = None
    refreshToken = None


class VerifySessionObject(PlainObject):
    sessionID = None


class CashInInquiryObject(PlainObject):
    token = None
    amount = None
    merchantTrxID = None
    trxDate = None


class CashInConfirmationObject(PlainObject):
    token = None
    amount = None
    merchantTrxID = None
    trxDate = None
    sessionID = None


class CheckTransactionalStatusObject(PlainObject):
    merchantTrxID = None
