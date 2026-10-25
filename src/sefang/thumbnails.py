"""Bounded validation of Telegram fallback thumbnails, never official cover art."""
import io
from PIL import Image

MAX_BYTES = 2 * 1048576
MAX_PIXELS = 4_000_000
DECODE_SECONDS = 2


def inspect_thumbnail(data: bytes | None) -> tuple[str | None, str]:
    if not data:
        return None, 'empty'
    if len(data) > MAX_BYTES:
        return None, 'too_large'
    try:
        with Image.open(io.BytesIO(data)) as image:
            if (image.format not in ('JPEG', 'PNG', 'WEBP') or getattr(image, 'is_animated', False)
                    or image.width * image.height > MAX_PIXELS):
                return None, 'invalid'
            image.load()
            # Exact decoded RGB zero only: brightness thresholds would hide dark content.
            if image.convert('RGB').getextrema() == ((0, 0), (0, 0), (0, 0)):
                return None, 'black'
            return Image.MIME[image.format], ''
    except (OSError, ValueError, Image.DecompressionBombError):
        return None, 'invalid'
