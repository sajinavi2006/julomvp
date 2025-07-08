import json
import logging
from rest_framework import status as http_status_codes
from rest_framework.response import Response
import requests
from requests.exceptions import Timeout
from juloserver.partnership.constants import APISourceFrom
from juloserver.partnership.models import PartnershipApiLog
from juloserver.partnership.clients.paths import LinkAjaApiUrls
from juloserver.partnership.clients.utils import LinkAjaUtils
from juloserver.partnership.clients.request_constructor import LinkAjaRequestDataConstructor
from juloserver.partnership.exceptions import LinkAjaClientException
from juloserver.partnership.services.services import call_slack_bot
from juloserver.julo.models import Partner


from typing import Dict

from juloserver.partnership.utils import partnership_detokenize_sync_object_model
from juloserver.pii_vault.constants import PiiVaultDataType, PiiSource

logger = logging.getLogger(__name__)


class LinkAjaClient(object):
    API_CALL_TIME_GAP = 15
    TIMEOUT_ATTEMPTS = 5

    @staticmethod
    def store_partnership_api_log(
            url: str, api_type: str, response: Response = None,
            request_body: Dict = None, partner_id: int = None,
            customer_id: int = None, application_id: int = None,
            distributor_id: int = None, error_message: str = None,
            query_param: str = None
    ) -> PartnershipApiLog:

        try:
            json_response = json.loads(response.content)
        except Exception:
            log_data = {
                "action": "store_partnership_api_log",
                "error": "Error parsing json response",
                "url": url,
                "api_type": api_type,
            }
            logger.error(log_data)
            json_response = None

        try:
            status_code = response.status_code
        except Exception:
            log_data = {
                "action": "store_partnership_api_log",
                "error": "Error parsing status code",
                "url": url,
                "api_type": api_type,
            }
            logger.error(log_data)
            status_code = None

        log = {
            "partner_id": partner_id,
            "customer_id": customer_id,
            "application_id": application_id,
            "api_url": url,
            "query_params": str(query_param),
            "api_type": api_type,
            "response_json": json_response,
            "http_status_code": status_code,
            "request_body_json": request_body,
            "error_message": error_message,
            "distributor_id": distributor_id,
            "api_from": APISourceFrom.EXTERNAL
        }

        log_created = PartnershipApiLog.objects.create(**log)
        return log_created

    @staticmethod
    def get_oath_token(partner_id):
        url, uri_path = LinkAjaApiUrls.build_url(
            LinkAjaApiUrls.GET_AUTH, LinkAjaRequestDataConstructor.GET)
        headers = LinkAjaRequestDataConstructor.construct_request_headers(
            LinkAjaApiUrls.GET_AUTH, LinkAjaRequestDataConstructor.GET, create_token=True)
        response = requests.get(url, headers=headers)
        if response.status_code == http_status_codes.HTTP_200_OK:
            access_token, refresh_token = LinkAjaUtils.get_tokens_from_response(response)
            LinkAjaUtils.set_access_token(access_token, partner_id)
            LinkAjaUtils.set_refresh_token(refresh_token, partner_id)
        LinkAjaClient.store_partnership_api_log(
            url, LinkAjaRequestDataConstructor.GET, response, query_param=uri_path,
            partner_id=partner_id
        )
        partner = Partner.objects.filter(id=partner_id).only('name').last()
        if response.status_code >= http_status_codes.HTTP_500_INTERNAL_SERVER_ERROR:
            call_slack_bot(partner.name, response.request.url, response.request.method,
                           response.request.headers, response.request.body, '',
                           response.status_code, "LinkAja server error")
        return response

    @staticmethod
    def refresh_token(partner_id):
        url, uri_path = LinkAjaApiUrls.build_url(
            LinkAjaApiUrls.REFRESH_TOKEN, LinkAjaRequestDataConstructor.POST)
        body = LinkAjaRequestDataConstructor.construct_refresh_token_body(partner_id)
        headers = LinkAjaRequestDataConstructor.construct_request_headers(
            LinkAjaApiUrls.REFRESH_TOKEN, LinkAjaRequestDataConstructor.POST,
            json.dumps(body), partner_id
        )
        response = requests.post(url, headers=headers, json=body)
        LinkAjaClient.store_partnership_api_log(
            url,
            LinkAjaRequestDataConstructor.POST,
            response,
            request_body=body,
            query_param=uri_path,
            partner_id=partner_id,
        )
        if response.status_code == http_status_codes.HTTP_200_OK:
            try:
                access_token, refresh_token = LinkAjaUtils.get_tokens_from_response(response)
            except LinkAjaClientException:
                response = LinkAjaClient.get_oath_token(partner_id)
                return response
            LinkAjaUtils.set_access_token(access_token, partner_id)
            LinkAjaUtils.set_refresh_token(refresh_token, partner_id)
        partner = Partner.objects.filter(id=partner_id).only('name').last()
        if response.status_code >= http_status_codes.HTTP_500_INTERNAL_SERVER_ERROR:
            call_slack_bot(partner.name, response.request.url, response.request.method,
                           response.request.headers, response.request.body, '',
                           response.status_code, "LinkAja server error")
        return response

    @staticmethod
    def verify_session_id(session_id, partner_id):
        url, uri_path = LinkAjaApiUrls.build_url(
            LinkAjaApiUrls.VERIFY_CUSTOMER, LinkAjaRequestDataConstructor.POST)
        body = LinkAjaRequestDataConstructor.construct_verify_session_body(session_id)
        headers = LinkAjaRequestDataConstructor.construct_request_headers(
            LinkAjaApiUrls.VERIFY_CUSTOMER, LinkAjaRequestDataConstructor.POST,
            json.dumps(body), partner_id
        )
        try:
            response = requests.post(url, headers=headers, json=body, timeout=15)
        except Timeout as e:
            LinkAjaClient.store_partnership_api_log(
                url,
                LinkAjaRequestDataConstructor.POST,
                query_param=uri_path,
                partner_id=partner_id,
                request_body=body,
                error_message='request timeout after 15 seconds',
            )
            raise e
        LinkAjaClient.store_partnership_api_log(
            url,
            LinkAjaRequestDataConstructor.POST,
            response,
            request_body=body,
            query_param=uri_path,
            partner_id=partner_id
        )
        if response.status_code == http_status_codes.HTTP_401_UNAUTHORIZED:
            LinkAjaClient.refresh_token(partner_id)
            response = LinkAjaClient.verify_session_id(session_id, partner_id)
            return response
        partner = Partner.objects.filter(id=partner_id).only('name').last()
        if response.status_code >= http_status_codes.HTTP_500_INTERNAL_SERVER_ERROR:
            call_slack_bot(partner.name, response.request.url, response.request.method,
                           response.request.headers, response.request.body, '',
                           response.status_code, "LinkAja server error")
        return response

    @staticmethod
    def cash_in_inquiry(customer_token, amount, merchant_txn_id, partner_id):
        url, uri_path = LinkAjaApiUrls.build_url(
            LinkAjaApiUrls.CASH_IN_INQUIRY, LinkAjaRequestDataConstructor.POST)
        body = LinkAjaRequestDataConstructor.construct_cashin_inquiry_body(
            customer_token, amount, merchant_txn_id)
        headers = LinkAjaRequestDataConstructor.construct_request_headers(
            LinkAjaApiUrls.CASH_IN_INQUIRY, LinkAjaRequestDataConstructor.POST,
            json.dumps(body), partner_id
        )
        try:
            response = requests.post(url, headers=headers, json=body, timeout=15)
        except Timeout as e:
            LinkAjaClient.store_partnership_api_log(
                url,
                LinkAjaRequestDataConstructor.POST,
                query_param=uri_path,
                partner_id=partner_id,
                request_body=body,
                error_message="request timeout after 15 seconds",
            )
            raise e
        LinkAjaClient.store_partnership_api_log(
            url,
            LinkAjaRequestDataConstructor.POST,
            response,
            request_body=body,
            query_param=uri_path,
            partner_id=partner_id,
        )
        if response.status_code == http_status_codes.HTTP_401_UNAUTHORIZED:
            LinkAjaClient.refresh_token(partner_id)
            response = LinkAjaClient.cash_in_inquiry(
                customer_token, amount, merchant_txn_id, partner_id)
            return response
        partner = Partner.objects.filter(id=partner_id).last()

        detokenize_partner = partnership_detokenize_sync_object_model(
            PiiSource.PARTNER,
            partner,
            customer_xid=None,
            fields_param=['name'],
            pii_type=PiiVaultDataType.KEY_VALUE,
        )

        if response.status_code >= http_status_codes.HTTP_500_INTERNAL_SERVER_ERROR:
            call_slack_bot(
                detokenize_partner.name,
                response.request.url,
                response.request.method,
                response.request.headers,
                response.request.body,
                '',
                response.status_code,
                "LinkAja server error",
            )
        return response

    @staticmethod
    def cash_in_confirmation(session_id, customer_token, amount, merchant_txn_id, partner_id):
        url, uri_path = LinkAjaApiUrls.build_url(
            LinkAjaApiUrls.CASH_IN_CONFIRMATION, LinkAjaRequestDataConstructor.POST)
        body = LinkAjaRequestDataConstructor.construct_cashin_confirmation_body(
            session_id, customer_token, amount, merchant_txn_id)
        headers = LinkAjaRequestDataConstructor.construct_request_headers(
            LinkAjaApiUrls.CASH_IN_CONFIRMATION, LinkAjaRequestDataConstructor.POST,
            json.dumps(body), partner_id
        )
        try:
            response = requests.post(url, headers=headers, json=body, timeout=15)
        except Timeout as e:
            LinkAjaClient.store_partnership_api_log(
                url,
                LinkAjaRequestDataConstructor.POST,
                request_body=body,
                query_param=uri_path,
                partner_id=partner_id,
                error_message="request timeout after 15 seconds",
            )
            raise e
        LinkAjaClient.store_partnership_api_log(
            url,
            LinkAjaRequestDataConstructor.POST,
            response,
            request_body=body,
            query_param=uri_path,
            partner_id=partner_id,
        )
        if response.status_code == http_status_codes.HTTP_401_UNAUTHORIZED:
            LinkAjaClient.refresh_token(partner_id)
            response = LinkAjaClient.cash_in_confirmation(
                session_id, customer_token, amount, merchant_txn_id, partner_id)
            return response
        partner = Partner.objects.filter(id=partner_id).last()

        detokenize_partner = partnership_detokenize_sync_object_model(
            PiiSource.PARTNER,
            partner,
            customer_xid=None,
            fields_param=['name'],
            pii_type=PiiVaultDataType.KEY_VALUE,
        )

        if response.status_code >= http_status_codes.HTTP_500_INTERNAL_SERVER_ERROR:
            call_slack_bot(
                detokenize_partner.name,
                response.request.url,
                response.request.method,
                response.request.headers,
                response.request.body,
                '',
                response.status_code,
                "LinkAja server error",
            )
        return response

    @staticmethod
    def check_transactional_status(merchant_txn_id: int, partner_id: int) -> Response:
        """
            Static Method for check the status of a transaction,
            for now only for LinkAja transactions
        """
        url, uri_path = LinkAjaApiUrls.build_url(
            path=LinkAjaApiUrls.CHECK_TRANSACTION_STATUS,
            http_method=LinkAjaRequestDataConstructor.POST
        )

        body = LinkAjaRequestDataConstructor.construct_check_transactional_status_body(
            merchant_txn_id=merchant_txn_id
        )

        headers = LinkAjaRequestDataConstructor.construct_request_headers(
            path=LinkAjaApiUrls.CHECK_TRANSACTION_STATUS,
            method=LinkAjaRequestDataConstructor.POST,
            body=json.dumps(body), partner_id=partner_id
        )

        try:
            response = requests.post(url, headers=headers, json=body, timeout=15)
        except Timeout as e:
            LinkAjaClient.store_partnership_api_log(
                url,
                LinkAjaRequestDataConstructor.POST,
                query_param=uri_path,
                partner_id=partner_id,
                error_message="request timeout after 15 seconds",
                request_body=body,
            )
            raise e

        partnership_api_log = LinkAjaClient.store_partnership_api_log(
            url=url,
            api_type=LinkAjaRequestDataConstructor.POST,
            response=response,
            request_body=body,
            query_param=uri_path,
            partner_id=partner_id,
        )

        # adding partnership api log to return response,
        # so that it can be used in PartnershipLogRetryTransactionCheck
        response.partnership_api_log = partnership_api_log

        # Handle if the response is unauthorized,
        # then refresh the token to get a new request check transaction

        if response.status_code == http_status_codes.HTTP_401_UNAUTHORIZED:
            LinkAjaClient.refresh_token(partner_id)
            response = LinkAjaClient.check_transactional_status(merchant_txn_id, partner_id)
            return response
        partner = Partner.objects.filter(id=partner_id).last()
        detokenize_partner = partnership_detokenize_sync_object_model(
            PiiSource.PARTNER,
            partner,
            customer_xid=None,
            fields_param=['name'],
            pii_type=PiiVaultDataType.KEY_VALUE,
        )
        if response.status_code >= http_status_codes.HTTP_500_INTERNAL_SERVER_ERROR:
            call_slack_bot(
                detokenize_partner.name,
                response.request.url,
                response.request.method,
                response.request.headers,
                response.request.body,
                '',
                response.status_code,
                "LinkAja server error",
            )
        return response
