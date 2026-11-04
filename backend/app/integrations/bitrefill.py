"""Hosted Bitrefill MCP, stateless HTTP. Only documented read capabilities.

Sources and unresolved contracts: docs/bitrefill-contract.md. Do not add guessed
price fields or enable buy-products until that contract is independently verified.
"""
import json
import logging
import time
from decimal import Decimal
from uuid import uuid4
from typing import NoReturn

import httpx
import toon_format

from app.core.config import Settings
from app.schemas.bitrefill import CreatedInvoice, Denomination, InvoiceObservation, Product, Quote

logger = logging.getLogger(__name__)
MCP_URL = 'https://api.bitrefill.com/mcp'
READ_TOOLS = {'search-products', 'get-product-details', 'get-invoice-by-id'}
PROVIDER_CODES = {'VALIDATION_ERROR', 'INVALID_INPUT', 'RESOURCE_NOT_FOUND', 'PERMISSION_DENIED',
                  'SERVICE_UNAVAILABLE', 'PAYMENT_UNCERTAIN', 'INTERNAL_ERROR'}
INVOICE_STATES = {'unpaid', 'payment_detected', 'payment_confirmed', 'pending', 'complete',
                  'blocked', 'denied', 'payment_error'}
ORDER_STATES = {'created', 'payment_detected', 'processing', 'delivered', 'failed', 'refunded'}


class ProviderError(Exception):
    def __init__(self, code: str, status_code: int = 502):
        self.code = code
        self.status_code = status_code
        # Never include provider messages, response bodies, URLs or credentials.
        super().__init__('Bitrefill integration error')


def bounded_string(value, maximum=128):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ProviderError('unsupported_response_contract')
    return value


class BitrefillClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def _rpc(self, tool: str, arguments: dict):
        if tool not in READ_TOOLS:
            raise ProviderError('checkout_contract_unverified', 503)
        key = self.settings.bitrefill_api_key
        if not key or not key.get_secret_value().strip():
            raise ProviderError('credentials_missing', 503)
        request_id = str(uuid4())
        payload = {'jsonrpc': '2.0', 'id': request_id, 'method': 'tools/call',
                   'params': {'name': tool, 'arguments': arguments}}
        for attempt in range(2):
            try:
                with httpx.Client(transport=self.transport, timeout=self.settings.bitrefill_timeout_seconds,
                                  follow_redirects=False, trust_env=False) as client:
                    with client.stream('POST', MCP_URL, json=payload, headers={
                        'Authorization': f'Bearer {key.get_secret_value()}',
                        'Accept': 'application/json, text/event-stream',
                    }) as response:
                        if response.status_code == 401:
                            raise ProviderError('credentials_rejected', 503)
                        if response.status_code == 429:
                            raise ProviderError('rate_limited', 503)
                        if response.status_code == 503:
                            raise ProviderError('SERVICE_UNAVAILABLE', 503)
                        if response.status_code != 200:
                            raise ProviderError('http_error')
                        parts, size = [], 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > 1_000_000:
                                raise ProviderError('response_too_large')
                            parts.append(chunk)
                        body = b''.join(parts).decode('utf-8')
                        if response.headers.get('content-type', '').split(';')[0] == 'text/event-stream':
                            messages = []
                            for event in body.replace('\r\n', '\n').split('\n\n'):
                                data = '\n'.join(line[5:].lstrip(' ') for line in event.splitlines() if line.startswith('data:'))
                                if data:
                                    messages.append(json.loads(data, parse_float=Decimal))
                            messages = [item for item in messages if item.get('id') == request_id]
                            if len(messages) != 1:
                                raise ProviderError('unsupported_response_contract')
                            envelope = messages[0]
                        else:
                            envelope = json.loads(body, parse_float=Decimal)
                if envelope.get('jsonrpc') != '2.0' or envelope.get('id') != request_id or 'error' in envelope:
                    raise ProviderError('rpc_error')
                result = envelope['result']
                if result.get('isError'):
                    try:
                        error = json.loads(result['content'][0]['text'])
                        code = error.get('code')
                    except (KeyError, IndexError, TypeError, ValueError):
                        code = None
                    raise ProviderError(code if code in PROVIDER_CODES else 'tool_error')
                if isinstance(result.get('structuredContent'), dict):
                    return result['structuredContent']
                content = result['content']
                if len(content) != 1 or content[0].get('type') != 'text':
                    raise ProviderError('unsupported_response_contract')
                text = content[0]['text']
                try:
                    return json.loads(text, parse_float=Decimal)
                except ValueError:
                    return toon_format.loads(text, parse_float=Decimal)
            except httpx.TimeoutException:
                error = ProviderError('timeout', 504)
            except httpx.TransportError:
                error = ProviderError('transport_error', 502)
            except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
                error = ProviderError('unsupported_response_contract')
            except ProviderError as exc:
                error = exc
            if attempt == 0 and error.code in {'timeout', 'transport_error', 'SERVICE_UNAVAILABLE'}:
                time.sleep(0.2)
                continue
            logger.warning('Bitrefill read failed: operation=%s code=%s', tool, error.code)
            raise error from None

    def _product(self, raw: dict) -> Product:
        try:
            # Documented product and package fields only; no raw response forwarding.
            product_id = bounded_string(raw['id'])
            packages = raw.get('packages', [])
            if not isinstance(packages, list) or len(packages) > 1000:
                raise ProviderError('unsupported_response_contract')
            denominations = []
            for package in packages:
                value = package.get('package_value')
                if value is not None:
                    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
                        raise ProviderError('unsupported_response_contract')
                    denominations.append(Denomination(package_value=bounded_string(str(value))))
            range_data = raw.get('range')
            value_range = None
            if isinstance(range_data, dict) and all(key in range_data for key in ('min', 'max', 'step')):
                value_range = {key: bounded_string(str(range_data[key])) for key in ('min', 'max', 'step')}
            optional = {}
            for key in ('name', 'country', 'currency', 'recipient_type'):
                if raw.get(key) is not None:
                    optional[key] = bounded_string(raw[key], 200)
            product_type = raw.get('type')
            return Product(id=product_id, product_type=bounded_string(product_type) if product_type else None,
                           denominations=denominations, denomination_range=value_range,
                           requires_prepayment=bool(raw.get('prepayment')), **optional)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ProviderError('unsupported_response_contract') from None

    def search(self, query: str, intent: str, country: str = 'US', product_type: str | None = None) -> list[Product]:
        arguments = {'query': query, 'intent': intent, 'country': country, 'per_page': 20}
        if product_type:
            arguments['product_type'] = product_type
        raw = self._rpc('search-products', arguments)
        if not isinstance(raw, dict) or not isinstance(raw.get('products'), list):
            raise ProviderError('unsupported_response_contract')
        return [self._product(item) for item in raw['products']]

    def details(self, product_id: str) -> Product:
        raw = self._rpc('get-product-details', {'product_id': product_id, 'currency': 'USD'})
        if not isinstance(raw, dict):
            raise ProviderError('unsupported_response_contract')
        product = self._product(raw)
        if product.id != product_id:
            raise ProviderError('product_identity_mismatch')
        return product

    def quote(self, product: Product, denomination: str, recipient: str | None) -> Quote:
        # Public docs do not establish final USD cost incl. fees, availability or
        # price-lock validity. Denomination/face value and USDC are NOT USD cost.
        raise ProviderError('quote_contract_unverified', 503)

    def ensure_checkout_supported(self) -> NoReturn:
        raise ProviderError('checkout_contract_unverified', 503)

    def create_invoice(self, quote: Quote, recipient: str | None) -> CreatedInvoice:
        if not self.settings.bitrefill_live_purchases_enabled:
            raise ProviderError('live_purchases_disabled', 503)
        self.ensure_checkout_supported()
        # Intentionally no buy-products dispatch. See verified-contract blocker.

    def invoice(self, invoice_id: str) -> InvoiceObservation:
        raw = self._rpc('get-invoice-by-id', {'invoice_id': invoice_id})
        try:
            if raw['invoice_id'] != invoice_id:
                raise ProviderError('invoice_identity_mismatch')
            status = raw['invoice_status']
            orders = raw.get('orders', [])
            if not isinstance(orders, list):
                raise ProviderError('unsupported_response_contract')
            return InvoiceObservation(
                invoice_id=invoice_id, invoice_status=status if status in INVOICE_STATES else 'unknown',
                order_statuses=[order.get('status') if order.get('status') in ORDER_STATES else 'unknown' for order in orders],
                product_ids=[bounded_string(order['product']['id']) if isinstance(order.get('product'), dict)
                             and 'id' in order['product'] else '' for order in orders],
            )
        except (KeyError, TypeError, AttributeError, ValueError):
            raise ProviderError('unsupported_response_contract') from None
