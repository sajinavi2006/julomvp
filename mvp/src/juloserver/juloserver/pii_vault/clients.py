from django.conf import settings
from juloserver.julo.exceptions import JuloException

import requests
import json
from juloserver.pii_vault.constants import PiiVaultService
from juloserver.pii_vault.exceptions import PIIDataNotFound

# Create your views here.


class PIIVaultClient:
    """
    A PIIVault rest wrapper
    It have function to tokenize and detokenize
    It is trust base authentication
    """

    def __init__(self, authentication):
        self.authentication = authentication

    def tokenize(self, data, schema="customer"):
        url = f"{settings.PII_VAULT_BASE_URL}/transform/{schema}/tokenize"
        body = {"records": data}
        result = self.post_request_call(url, body)
        return result["records"]

    def detokenize(self, data, schema="customer", timeout=None):
        url = f"{settings.PII_VAULT_BASE_URL}/transform/{schema}/detokenize"
        body = {"records": data}
        result = self.post_request_call(url, body, timeout)
        return result["records"]

    def post_request_call(self, url, body, timeout=None):
        response = requests.request(
            "POST",
            url,
            headers={"Content-Type": "application/json", "authentication": self.authentication},
            data=json.dumps(body),
            timeout=timeout,
        )
        if response.status_code == 200:
            result = response.json()
            return result
        raise JuloException('Vault service call failed')

    def general_tokenize(self, data):
        url = f"{settings.PII_VAULT_BASE_URL}/general-transform/tokenize"
        body = {"records": data}
        result = self.post_request_call(url, body)
        return result["records"]

    def general_detokenize(self, data, timeout=None):
        url = f"{settings.PII_VAULT_BASE_URL}/general-transform/detokenize"
        body = {"records": data}
        result = self.post_request_call(url, body, timeout)
        return result["records"]
    
    def exact_lookup(self, data, timeout=None):
        url = f"{settings.PII_VAULT_BASE_URL}/lookup/exactmatch/customer"
        body = {"value": data}
        result = self.post_request_call(url, body, timeout)
        if result["records"].get("status_code",200) == 500:
            raise JuloException('PII lookup Failed')
        elif result["records"].get("status_code",200) == 404:
            raise PIIDataNotFound()
        output=[result["records"]["token"]]
        if result["records"].get("replacement_token"):
            output.append(result["records"].get("replacement_token"))
        return output
    
    def general_exact_lookup(self, data, timeout=None):
        url = f"{settings.PII_VAULT_BASE_URL}/lookup/exactmatch/kv"
        body = {"value": data}
        result = self.post_request_call(url, body, timeout)
        if result["records"].get("status_code",200) == 500:
            raise JuloException('PII lookup Failed')
        elif result["records"].get("status_code",200) == 404:
            raise PIIDataNotFound()
        output=[result["records"]["token"]]
        if result["records"].get("replacement_token"):
            output.append(result["records"].get("replacement_token"))
        return output


def get_pii_vault_client(service=None):
    service_token_map = {
        PiiVaultService.ONBOARDING: settings.PII_VAULT_ONBOARDING_TOKEN,
        PiiVaultService.PARTNERSHIP: settings.PII_VAULT_PARTNERSHIP_ONBOARDING_TOKEN,
        PiiVaultService.COLLECTION: settings.PII_VAULT_COLLECTION_TOKEN,
        PiiVaultService.REPAYMENT: settings.PII_VAULT_REPAYMENT_TOKEN,
        PiiVaultService.CUSTOMER_EXCELLENCE: settings.PII_VAULT_CUSTOMER_EXCELLENCE_TOKEN,
        PiiVaultService.ANTIFRAUD: settings.PII_VAULT_ANTIFRAUD_TOKEN,
        PiiVaultService.UTILIZATION: settings.PII_VAULT_UTILIZATION_TOKEN,
        PiiVaultService.LOAN: settings.PII_VAULT_LOAN_TOKEN,
        PiiVaultService.PLATFORM: settings.PII_VAULT_PLATFORM_TOKEN,
    }
    token = service_token_map.get(service, settings.PII_VAULT_JULOVER_TOKEN)
    return PIIVaultClient(authentication=token)
