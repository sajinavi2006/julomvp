import json
import logging
import random
from builtins import object

logger = logging.getLogger(__name__)


class DropDownBase(object):
    dropdown = None
    version = None
    file_name = None

    def write(self, buf, dropdown, version, product_line_code, force_write=False):
        try:
            if self.dropdown == dropdown:

                # without compare dropdown version between server and app version request
                if force_write:
                    logger.info(
                        {
                            "message": "force write for some dropdown",
                            "dropdown": self.dropdown,
                            "server_version": self.version,
                            "app_version": version,
                            "force_write": force_write,
                        }
                    )
                    buf.writestr(self.file_name, self._get_data(product_line_code, True))
                    return {self.file_name: self.version}

                # compare dropdown version between server and app version request
                if int(self.version) > int(version):
                    logger.info(
                        {
                            "message": "Writing dropdown data",
                            "dropdown": self.dropdown,
                            "server_version": self.version,
                            "app_version": version,
                            "force_write": force_write,
                        }
                    )
                    buf.writestr(self.file_name, self._get_data(product_line_code))
                    return {self.file_name: self.version}

        except ValueError:
            pass

    def _get_data(self, product_line_code, randomize=False):

        if randomize:
            random.shuffle(self.DATA)

        data = {'version': self.version, 'data': self.DATA}
        return json.dumps(data)
