from abc import ABC, abstractmethod
import asyncio
import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import ipaddress
import json
from pathlib import Path
import socket
from urllib.parse import urlparse
import httpx
import yaml
from pydantic import ValidationError
from bac.vendor.bookforge.models.page import PageDocument


class ProviderError(Exception):
    def __init__(self, code: str, retryable=True, retry_after=0):
        super().__init__(code)
        self.code, self.retryable, self.retry_after = code, retryable, retry_after


class VisionProvider(ABC):
    @abstractmethod
    async def extract(self, image: Path, page: int, width: int, height: int):
        """Return validated PageDocument, usage; implementations never write Markdown."""


async def validate_base_url(url: str, allow_private=False):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Base URL must be an HTTP(S) URL without credentials/query/fragment')
    if not allow_private and parsed.scheme != 'https':
        raise ValueError('HTTPS is required for remote model APIs')
    if allow_private:
        return
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or 443, 0, socket.SOCK_STREAM)
    except OSError:
        raise ValueError('Model API hostname could not be resolved') from None
    if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Private/reserved model addresses are disabled')


def retry_after_seconds(value):
    if not value:
        return 0
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError):
            return 0
    return min(3600, max(0, seconds))


class OpenAICompatibleProvider(VisionProvider):
    def __init__(self, api_key, base_url, model, settings, output_mode='json_object', max_tokens=12000, transport=None):
        if output_mode not in ('json_object', 'json_schema', 'none'):
            raise ValueError('Unknown structured output mode')
        self.api_key, self.base_url, self.model = api_key, base_url.rstrip('/'), model
        self.settings, self.output_mode, self.max_tokens, self.transport = settings, output_mode, max_tokens, transport
        prompts = yaml.safe_load(settings.prompt_file.read_text())
        self.prompt = prompts['vision']
        self.contract = prompts['json_contract']

    async def extract(self, image, page, width, height):
        if self.transport is None:
            await validate_base_url(self.base_url, self.settings.allow_private_model_urls)
        schema = PageDocument.model_json_schema()
        context = f'PDF page={page}; image width={width}; height={height}.'
        if self.output_mode != 'json_schema':
            context += ' JSON contract: ' + self.contract
        body = {
            'model': self.model, 'max_tokens': self.max_tokens,
            'messages': [
                {'role': 'system', 'content': self.prompt},
                {'role': 'user', 'content': [
                    {'type': 'text', 'text': context},
                    {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(image.read_bytes()).decode()}}
                ]}
            ],
        }
        if self.output_mode == 'json_object':
            body['response_format'] = {'type': 'json_object'}
        elif self.output_mode == 'json_schema':
            body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'book_page', 'strict': False, 'schema': schema}}
        endpoint = self.base_url if self.base_url.endswith('/chat/completions') else self.base_url + '/chat/completions'
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout, transport=self.transport, follow_redirects=False, trust_env=False) as client:
                async with client.stream('POST', endpoint, json=body, headers={'Authorization': 'Bearer ' + self.api_key}) as response:
                    if response.status_code != 200:
                        code = response.status_code
                        raise ProviderError(f'HTTP_{code}', code in (408, 409, 425, 429) or code >= 500,
                                            retry_after_seconds(response.headers.get('Retry-After')))
                    result = bytearray()
                    async for chunk in response.aiter_bytes():
                        result.extend(chunk)
                        if len(result) > 8 * 1024**2:
                            raise ProviderError('RESPONSE_TOO_LARGE', False)
            payload = json.loads(result)
            choice = payload['choices'][0]
            if choice.get('finish_reason') == 'length':
                raise ProviderError('OUTPUT_TRUNCATED')
            content = choice['message']['content']
            if isinstance(content, list):
                content = ''.join(x.get('text', '') for x in content if x.get('type') == 'text')
            # Some compatible providers wrap JSON despite instructions.
            text = content.strip()
            if text.startswith('```') and text.endswith('```'):
                text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
            doc = PageDocument.model_validate_json(text)
            usage = payload.get('usage', {})
            return doc, {k: v for k, v in usage.items() if isinstance(v, (int, float))}
        except ProviderError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError):
            raise ProviderError('NETWORK_OR_TIMEOUT') from None
        except (json.JSONDecodeError, ValidationError, KeyError, IndexError, TypeError, AttributeError):
            raise ProviderError('INVALID_STRUCTURED_JSON') from None
        except httpx.HTTPError:
            raise ProviderError('TRANSPORT_ERROR') from None
