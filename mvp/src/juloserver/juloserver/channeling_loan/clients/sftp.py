import logging
import io
from typing import Union

import pysftp
from paramiko import RSAKey

logger = logging.getLogger(__name__)


class SFTPClient:
    def __init__(
        self,
        host: str,
        username: str,
        port: int,
        password: str = None,
        rsa_private_key: str = None,
        remote_directory: str = '',
    ):
        self.host = host
        self.username = username
        self.port = int(port)
        self.password = password
        self.rsa_private_key = rsa_private_key
        self.remote_directory = remote_directory
        self.action_path = "juloserver.channeling_loan.clients.sftp.SFTPClient"

    def _sftp_connection(self) -> pysftp.Connection:
        # disable host key verification (because connect to a known server)
        # to allow connecting using password if we have instead of RSA key
        cnopts = pysftp.CnOpts()
        cnopts.hostkeys = None

        return pysftp.Connection(
            host=self.host,
            username=self.username,
            port=self.port,
            private_key=RSAKey(file_obj=io.StringIO(self.rsa_private_key))
            if self.rsa_private_key is not None
            else None,
            password=self.password,
            cnopts=cnopts,
        )

    def upload(self, content: Union[str, bytes], remote_path: str) -> None:
        """Save content to a file in SFTP server"""
        if self.remote_directory:
            remote_path = "{}/{}".format(self.remote_directory, remote_path)

        with self._sftp_connection() as connection:
            content_bytes = content.encode() if isinstance(content, str) else content
            connection.putfo(flo=io.BytesIO(content_bytes), remotepath=remote_path)
            logger.info(
                {
                    "action": "{}.upload_to_sftp_server".format(self.action_path),
                    "message": "File uploaded successfully",
                    "content_length": len(content),
                    "remote_path": remote_path,
                    "host": self.host,
                }
            )

    def download(self, remote_path: str) -> bytes:
        """Download file from SFTP server and return its content as bytes.
        Don't return as string because it can be binary file."""
        if self.remote_directory:
            remote_path = "{}/{}".format(self.remote_directory, remote_path)

        with self._sftp_connection() as connection:
            in_memory_io = io.BytesIO()
            connection.getfo(remotepath=remote_path, flo=in_memory_io)
            logger.info(
                {
                    "action": "{}.download_from_sftp_server".format(self.action_path),
                    "message": "File downloaded successfully",
                    "remote_path": remote_path,
                    "host": self.host,
                }
            )
        return in_memory_io.getvalue()

    def list_dir(self, remote_dir_path: str) -> list:
        """List files/directories in the remote directory"""
        if self.remote_directory:
            remote_dir_path = "{}/{}".format(self.remote_directory, remote_dir_path)

        with self._sftp_connection() as connection:
            return connection.listdir(remote_dir_path)
