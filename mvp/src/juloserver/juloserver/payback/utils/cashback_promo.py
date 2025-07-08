from builtins import str
import time
from juloserver.julo.utils import generate_hex_sha256

def generate_token(pic_email, id, udate):
    return generate_hex_sha256(str(pic_email) + str(id) + str(time.mktime(udate.timetuple())))