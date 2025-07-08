import json
import math
from juloserver.partnership.models import PartnershipConfig
from juloserver.partnership.exceptions import LinkAjaClientException
from juloserver.julo.services2 import get_redis_client


class LinkAjaUtils(object):
    @staticmethod
    def get_access_token(partner_id):
        access_token = LinkAjaUtils.get_redis_key(
            "{}_partnership_access_token".format(str(partner_id)))
        if access_token:
            return access_token
        partnership_config = PartnershipConfig.objects.filter(
            partner_id=partner_id,
            partner__is_active=True
        ).last()
        if not partnership_config:
            raise LinkAjaClientException("Invalid Partnership Configuration")
        access_token = partnership_config.access_token
        return access_token

    @staticmethod
    def get_refresh_token(partner_id):
        refresh_token = LinkAjaUtils.get_redis_key(
            "{}_partnership_refresh_token".format(str(partner_id)))
        if refresh_token:
            return refresh_token
        partnership_config = PartnershipConfig.objects.filter(
            partner_id=partner_id,
            partner__is_active=True
        ).last()
        if not partnership_config:
            raise LinkAjaClientException("Invalid Partnership Configuration")
        refresh_token = partnership_config.refresh_token
        return refresh_token

    @staticmethod
    def set_access_token(access_token, partner_id):
        LinkAjaUtils.set_redis_key("{}_partnership_access_token".format(
            str(partner_id)), access_token)
        partnership_config = PartnershipConfig.objects.filter(
            partner_id=partner_id,
            partner__is_active=True
        ).last()
        if not partnership_config:
            raise LinkAjaClientException("Invalid Partnership Configuration")
        partnership_config.access_token = access_token
        partnership_config.save()
        return access_token

    @staticmethod
    def set_refresh_token(refresh_token, partner_id):
        LinkAjaUtils.set_redis_key("{}_partnership_refresh_token".format(
            str(partner_id)), refresh_token)
        partnership_config = PartnershipConfig.objects.filter(
            partner_id=partner_id,
            partner__is_active=True
        ).last()
        if not partnership_config:
            raise LinkAjaClientException("Invalid Partnership Configuration")
        partnership_config.refresh_token = refresh_token
        partnership_config.save()
        return refresh_token

    @staticmethod
    def format_amount_linkaja(amount):
        LINKAJA_AMOUNT_LENGTH = 10
        str_amount = str(math.floor(amount))
        formatted_amount = str_amount.rjust(LINKAJA_AMOUNT_LENGTH, '0') + '00'
        return formatted_amount

    @staticmethod
    def get_tokens_from_response(response):
        response_body = json.loads(response.content)
        if response_body['status'] == '00':
            access_token = response_body['data']['accessToken']
            refresh_token = response_body['data']['refreshToken']
        else:
            raise LinkAjaClientException("Unexpected Response")
        return access_token, refresh_token

    @staticmethod
    def get_redis_key(key):
        redis_client = get_redis_client()
        value = redis_client.get(key)
        return value

    @staticmethod
    def set_redis_key(key, value):
        redis_client = get_redis_client()
        redis_client.set(key, value)
        return value
