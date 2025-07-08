import requests
import time
from datetime import datetime
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class KangtauClient(object):
    def __init__(self, base_url: str, company_id: str, project_id: str, integration_token: str):
        self.base_url = base_url
        self.company_id = company_id
        self.project_id = project_id
        self.integration_token = integration_token

    def cms_user_authentication(
        self, email: str, password: str, retries=3, delay=2, timeout: float = 7.0
    ) -> str:
        """
        Authenticate to Kangtau CMS API and return the accessToken.

        Raises:
            RuntimeError: on timeout, HTTP error, OTP challenge, missing token, etc.
        """
        for attempt in range(retries):
            url = f"{self.base_url}/auth/otp/login"
            payload = {"email": email, "password": password}

            try:
                resp = requests.post(url, json=payload, timeout=timeout)
                resp.raise_for_status()
            except requests.exceptions.Timeout:
                raise RuntimeError("Auth request to Kangtau timed out")
            except requests.exceptions.HTTPError as http_err:
                raise RuntimeError(
                    f"Kangtau auth HTTP error: {http_err} (status {resp.status_code})"
                )
            except requests.RequestException as err:
                raise RuntimeError(f"Failed to authenticate with Kangtau: {err}")

            data = resp.json()

            # Extract and validate token
            try:
                token = data["user"]["accessToken"]
            except (KeyError, TypeError):
                raise RuntimeError(f"No accessToken found in response: {data!r}")
            except requests.RequestException as e:
                if attempt == retries - 1:
                    raise RuntimeError(f"Failed to authenticate with Kangtau: {e}")
                time.sleep(delay)
            if not isinstance(token, str) or not token:
                raise RuntimeError(f"Invalid accessToken returned: {token!r}")

            return token

    def get_campaign_list(
        self,
        access_token: str,
        page: int = 1,
        search_key: str = "",
        take: int = 20,
        timeout: float = 15.0,
    ) -> dict:
        """
        Fetch a paginated list of campaigns from Kangtau CMS.

        Args:
            access_token (str): JWT access token from kangtau_get_access_token().
            page (int): 1-based page number.
            search_key (str): Free-text filter.
            take (int): Number of items per page.
            timeout (float): Request timeout in seconds.

        Returns:
            dict: Parsed JSON response from the /campaigns/list endpoint.

        Raises:
            RuntimeError: On timeout, HTTP error, or malformed response.
        """
        company_id = self.company_id
        url = f"{self.base_url}/campaigns/list"
        params = {"page": page, "searchKey": search_key, "take": take}
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "X-Company-Id": company_id,
        }

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            raise RuntimeError("Campaign list request to Kangtau timed out")
        except requests.exceptions.HTTPError as http_err:
            raise RuntimeError(
                f"Kangtau campaign list HTTP error: {http_err} (status {resp.status_code})"
            )
        except requests.RequestException as err:
            raise RuntimeError(f"Failed to fetch Kangtau campaigns: {err}")

        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(f"Invalid JSON received: {resp.text!r}")

        return data

    def get_campaign_remark_report_download_urls(
        self,
        campaign_name: str,
        start_date: str,
        end_date: str,
        report_name: str = "Campaign Remark Report",
    ) -> dict:
        """
        Download the “Campaign Remark Report” from Kangtau.

        Args:
            campaign_name (str): The exact campaign name.
            start_date (str): Start date in YYYY-MM-DD format.
            end_date (str): End date in YYYY-MM-DD format.
            report_name (str): The “reportName” field (defaults to Campaign Remark Report).

        Returns:
            dict: Parsed JSON report payload.

        Raises:
            RuntimeError: On missing env var, timeout, HTTP errors, or malformed JSON.
        """
        url = f"{self.base_url}/integration/reports/download"
        token = self.integration_token
        project_id = self.project_id
        headers = {
            "Authorization": f"Token {token}",
            "X-Project-ID": project_id,
            "Content-Type": "application/json",
        }
        start_date = KangtauClient.extract_date_safe(start_date)
        end_date = KangtauClient.extract_date_safe(end_date)
        payload = {
            "reportName": report_name,
            "outputType": "json",
            "parameters": [
                {"name": "campaignName", "value": campaign_name},
                {"name": "dateRange", "value": f"{start_date}~{end_date}"},
            ],
        }

        try:
            resp = requests.post(url, headers=headers, json=payload)
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            raise RuntimeError("Download report request to Kangtau timed out")
        except requests.exceptions.HTTPError as http_err:
            raise RuntimeError(
                f"Kangtau download report HTTP error: {http_err} (status {resp.status_code})"
            )
        except requests.RequestException as err:
            raise RuntimeError(f"Failed to download Kangtau report: {err}")

        try:
            return resp.json()
        except ValueError:
            raise RuntimeError(f"Invalid JSON in download response: {resp.text!r}")

    def extract_date_safe(date_string: str) -> str:
        try:
            dt = datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%S.%fZ")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return date_string

    def download_report(self, url: str, timeout: float = 120.0) -> List[Dict[str, Any]]:
        """
        Download a Kangtau report given its direct URL and return the parsed JSON.

        Args:
            url (str): The full URL to the report (e.g.
                "https://storage.googleapis.com/.../campaign-remark-report-1745382223390.json").
            timeout (float): Seconds to wait for the request before timing out.

        Returns:
            dict: The JSON payload of the report.

        Raises:
            RuntimeError: On timeout, HTTP error, or invalid/missing JSON.
        """
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            raise RuntimeError(f"Download timed out when fetching report from {url}")
        except requests.exceptions.HTTPError as http_err:
            raise RuntimeError(
                f"HTTP error while downloading report: {http_err} (status {resp.status_code})"
            )
        except requests.RequestException as err:
            raise RuntimeError(f"Failed to download report from {url}: {err}")

        try:
            return resp.json()
        except ValueError:
            raise RuntimeError(f"Invalid JSON in report at {url}: {resp.text!r}")

    def get_customer_form_list(
        self,
        page: int = 1,
        search_key: str = "",
        take: int = 20,
        timeout: float = 15.0,
    ) -> dict:
        """
        Fetch a paginated list of customer forms from Kangtau CMS.

        Args:
            page (int): 1-based page number.
            search_key (str): Free-text filter.
            take (int): Number of items per page.
            timeout (float): Request timeout in seconds.

        Returns:
            dict: Parsed JSON response from the /customer-forms/list endpoint.

        Raises:
            RuntimeError: On timeout, HTTP error, or malformed response.
        """
        project_id = self.project_id
        url = f"{self.base_url}/integration/customers/form/list"
        params = {"page": page, "searchKey": search_key, "take": take}
        headers = {
            "Accept": "application/json",
            "Authorization": f"Token {self.integration_token}",
            "X-Project-ID": project_id,
        }

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            raise RuntimeError("Customer form list request to Kangtau timed out")
        except requests.exceptions.HTTPError as http_err:
            raise RuntimeError(
                f"Kangtau customer form list HTTP error: {http_err} (status {resp.status_code})"
            )
        except requests.RequestException as err:
            raise RuntimeError(f"Failed to fetch Kangtau customer forms: {err}")

        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(f"Invalid JSON received: {resp.text!r}")

        return data

    def get_customer_statistic(
        self,
        timeout: float = 120.0,
    ) -> dict:
        """
        Fetch a paginated list of customer statistics from Kangtau CMS.

        Args:
            timeout (float): Request timeout in seconds.

        Returns:
            dict: Parsed JSON response from the /customers/statistic/detail endpoint.

        Raises:
            RuntimeError: On timeout, HTTP error, or malformed response.
        """
        project_id = self.project_id
        url = f"{self.base_url}/integration/customers/statistic/detail"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Token {self.integration_token}",
            "X-Project-ID": project_id,
        }

        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            raise RuntimeError("Customer statistic request to Kangtau timed out")
        except requests.exceptions.HTTPError as http_err:
            raise RuntimeError(
                f"Kangtau customer statistic HTTP error: {http_err} (status {resp.status_code})"
            )
        except requests.RequestException as err:
            raise RuntimeError(f"Failed to fetch Kangtau customer statistics: {err}")

        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(f"Invalid JSON received: {resp.text!r}")

        return data

    def create_customer_form(
        self, name: str, customerAttributes: list, timeout: float = 15.0
    ) -> dict:
        """
        Create a customer form in Kangtau CMS.

        Args:
            name (str): The name of the customer form.
            customerAttributes (list): List of dictionaries with attribute details.
            timeout (float): Request timeout in seconds.

        Returns:
            dict: Parsed JSON response from the API.

        Raises:
            RuntimeError: On timeout, HTTP error, or malformed response.
        """
        url = f"{self.base_url}/integration/customers/form/create"
        headers = {
            "Authorization": f"Token {self.integration_token}",
            "X-Project-ID": self.project_id,
            "Content-Type": "application/json",
        }
        payload = {
            "name": name,
            "customerAttributes": customerAttributes,
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            raise RuntimeError("Customer form create request to Kangtau timed out")
        except requests.exceptions.HTTPError as http_err:
            raise RuntimeError(
                f"Kangtau customer form create HTTP error: {http_err} (status {resp.status_code})"
            )
        except requests.RequestException as err:
            raise RuntimeError(f"Failed to create Kangtau customer form: {err}")

        try:
            return resp.json()
        except ValueError:
            raise RuntimeError(f"Invalid JSON received: {resp.text!r}")

    def upsert_bulk_customer_data(
        self,
        customerFormId: str,
        fields: List[str],
        data: List[Dict[str, Any]],
        timeout: float = 300.0,
    ) -> dict:
        """
        Upsert bulk customer data in Kangtau CMS.

        Args:
            customerFormId (str): The ID of the customer form.
            fields (List[str]): List of fields to upsert.
            data (List[Dict[str, Any]]): List of customer data dictionaries. Max 1000 entries.
            timeout (float): Request timeout in seconds.

        Returns:
            dict: Parsed JSON response from the API.

        Raises:
            ValueError: If more than 1000 data items are provided.
            RuntimeError: On timeout, HTTP error, or malformed response.
        """
        if len(data) > 1000:
            raise ValueError("The maximum number of data items per request is 1000.")

        url = f"{self.base_url}/integration/customers/upsert/bulk"
        headers = {
            "Authorization": f"Token {self.integration_token}",
            "X-Project-ID": self.project_id,
            "Content-Type": "application/json",
        }
        payload = {
            "customerFormId": customerFormId,
            "fields": fields,
            "data": data,
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            raise RuntimeError("Bulk upsert request to Kangtau timed out")
        except requests.exceptions.HTTPError as http_err:
            raise RuntimeError(
                f"Kangtau bulk upsert HTTP error: {http_err} (status {resp.status_code})"
            )
        except requests.RequestException as err:
            raise RuntimeError(f"Failed to upsert customer data: {err}")

        try:
            return resp.json()
        except ValueError:
            raise RuntimeError(f"Invalid JSON received: {resp.text!r}")
