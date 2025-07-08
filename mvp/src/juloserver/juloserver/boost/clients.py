from builtins import object


class JuloScraperClient(object):
    def __init__(self, scraper_token, scraper_base_url):
        self.scraper_base_url = scraper_base_url
        self.scraper_token = scraper_token

    def get_bank_scraping_status(self, application_id):
        """
        Get the Latest status of the bank scrapping
        :param application_id:
        :return: Result from the scraper - verified/pending/Not verified
        """
        return {}

        # headers = {'Authorization': 'Token %s' % self.scraper_token}
        # response = requests.get(
        #     self.scraper_base_url + '/api/etl/v1/bank_status/' + str(application_id) + '/',
        #     headers=headers,
        # )
        # if response.status_code not in [HTTP_200_OK]:
        #     err_msg = "failed to get status from scraper " "For application={}:{} ".format(
        #         application_id, response.text
        #     )
        #     raise JuloException(err_msg)
        # result = json.loads(response.text, object_pairs_hook=OrderedDict)
        # return result
