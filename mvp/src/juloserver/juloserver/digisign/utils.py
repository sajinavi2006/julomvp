from dataclasses import dataclass
import base64
from typing import Optional


@dataclass
class DataUrlMetadata:
    mime_type: str
    content: bytes

    @property
    def size(self) -> int:
        """Get content size in bytes"""
        return len(self.content)

    @property
    def is_pdf(self) -> bool:
        return self.mime_type == 'application/pdf'


def parse_data_signed_document(data_url: str) -> Optional[DataUrlMetadata]:
    """Parse data URL and return metadata"""
    try:
        data_url = data_url.strip()
        header, base64_data = data_url.split(',', 1)
        mime_type = header.split(';')[0].replace('data:', '')
        content = base64.b64decode(base64_data)

        return DataUrlMetadata(
            mime_type=mime_type,
            content=content
        )
    except Exception as e:
        raise ValueError(f"Failed to parse data URL: {str(e)}")
