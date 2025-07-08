from builtins import object
from builtins import str
import hashlib
import base64
import hmac
from django.utils import timezone
import uuid
from juloserver.partnership.clients.utils import LinkAjaUtils
from juloserver.partnership.clients.request_objects import *

from django.conf import settings
from typing import Dict


class LinkAjaRequestDataConstructor(object):
    POST = "POST"
    GET = "GET"
    PUT = "PUT"

    @staticmethod
    def create_msg_id():
        return str(uuid.uuid4().hex)

    @staticmethod
    def create_transaction_id():
        return str(uuid.uuid4().hex)

    @staticmethod
    def construct_request_headers(
            path: str, method: str, body: str = "",
            partner_id: int = None, create_token: int = False) -> Dict:
        """
            Constructs the headers for the request
            for now only for LinkAja Header Authorization
        """

        username = settings.LINKAJA_API_USERNAME
        secret_key = settings.LINKAJA_API_SECRET_KEY
        algorithm = settings.LINKAJA_API_ALGORITHM

        digest = hashlib.sha256(body.encode('utf-8')).digest()
        d_digest = "SHA-256=%s" % base64.b64encode(digest).decode('utf-8')

        now_date = timezone.now().strftime('%a, %d %b %Y %H:%M:%S %Z')
        signing_string = "date: %s\n%s %s HTTP/1.1\ndigest: %s" % (
            now_date, method, path, d_digest)
        signature = hmac.new(
            key=secret_key.encode('utf-8'),
            msg=signing_string.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        d_signature = base64.b64encode(signature).decode()

        auth = "hmac username=\"%s\", algorithm=\"%s\", headers=\"date request-line digest\"," \
               " signature=\"%s\"" % (username, algorithm, d_signature)
        headers = {
            "Authorization": auth,
            "Digest": d_digest,
            "Date": now_date
        }
        if not create_token:
            headers["Access-Token"] = LinkAjaUtils.get_access_token(partner_id)

        return headers

    @staticmethod
    def construct_refresh_token_body(partner_id):
        access_token = LinkAjaUtils.get_access_token(partner_id)
        refresh_token = LinkAjaUtils.get_refresh_token(partner_id)
        refresh_body = RefreshObject()
        refresh_body.accessToken = access_token
        refresh_body.refreshToken = refresh_token
        return refresh_body.to_dict()

    @staticmethod
    def construct_verify_session_body(session_id):
        verify_session = VerifySessionObject()
        verify_session.sessionID = session_id
        return verify_session.to_dict()

    @staticmethod
    def construct_cashin_inquiry_body(customer_token, amount, merchant_txn_id):
        now_date = timezone.now().isoformat()
        cashin_inquiry = CashInInquiryObject()
        cashin_inquiry.token = customer_token
        cashin_inquiry.amount = LinkAjaUtils.format_amount_linkaja(amount)
        cashin_inquiry.merchantTrxID = merchant_txn_id
        cashin_inquiry.trxDate = now_date
        return cashin_inquiry.to_dict()

    @staticmethod
    def construct_cashin_confirmation_body(
            session_id, customer_token, amount, merchant_txn_id):
        now_date = timezone.now().isoformat()
        cashin_confirmation = CashInConfirmationObject()
        cashin_confirmation.token = customer_token
        cashin_confirmation.amount = LinkAjaUtils.format_amount_linkaja(amount)
        cashin_confirmation.merchantTrxID = merchant_txn_id
        cashin_confirmation.trxDate = now_date
        cashin_confirmation.sessionID = session_id
        return cashin_confirmation.to_dict()

    @staticmethod
    def construct_check_transactional_status_body(merchant_txn_id: int) -> Dict:
        check_transactional_status = CheckTransactionalStatusObject()
        check_transactional_status.merchantTrxID = merchant_txn_id
        return check_transactional_status.to_dict()
