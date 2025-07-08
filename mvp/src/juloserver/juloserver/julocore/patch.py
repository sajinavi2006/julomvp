import logging
import sys
from ssl import (
    SSLError,
    SSLSocket,
    SSL_ERROR_EOF,
)

logger = logging.getLogger(__name__)


def _ssl_socket_read(self, len=1024, buffer=None):
    """
    Monkey Patch SSLSocket.read function in python3.7/ssl.py
    """
    self._checkClosed()
    if self._sslobj is None:
        raise ValueError("Read on closed or unwrapped SSL socket.")
    try:
        if buffer is not None:
            return self._sslobj.read(len, buffer)
        else:
            return self._sslobj.read(len)
    except SSLError as x:
        if x.args[0] == SSL_ERROR_EOF and self.suppress_ragged_eofs:
            if buffer is not None:
                return 0
            else:
                return b''

        # Start of Patch
        if x.reason and x.reason in 'KRB5_S_TKT_NYV' and self.suppress_ragged_eofs:
            logger.error("SSL EOL: KRB5_S_TKT_NYV is captured")
            if buffer is not None:
                return 0
            else:
                return b''
        # End of Patch

        else:
            raise


class SSLEolPatchManager:
    def __enter__(self):
        self._original_read = SSLSocket.read
        version = sys.version_info
        # Patch only for python3.7
        if version.major == 3 and version.minor <= 7:
            SSLSocket.read = _ssl_socket_read

    def __exit__(self, exc_type, exc_value, exc_tb):
        if not self._original_read:
            return
        SSLSocket.read = self._original_read
