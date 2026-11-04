"""GET-only personal REST access assessment; no checkout adapter or writes.

Run: python -m app.integrations.verify_bitrefill_rest
No invoice bodies, credentials, account IDs or redemption material are returned.
"""
import json
import re
from uuid import UUID
from decimal import Decimal

import httpx

from app.core.config import Settings, get_settings
from app.integrations.bitrefill import ProviderError, bounded_string

REST_BASE = 'https://api.bitrefill.com/v2'
READ_PATHS = ('/ping', '/accounts/balance', '/products/swiggy-money-india', '/invoices?limit=1')


class RestAccessVerifier:
    """Separate from the purchase workflow; deliberately has no POST method."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings, self.transport = settings, transport

    def _read(self, path):
        invoice_read = re.fullmatch(r'/invoices/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', path)
        if path not in READ_PATHS and invoice_read is None:
            raise ProviderError('rest_read_not_allowed')
        key = self.settings.bitrefill_api_key
        if key is None or not key.get_secret_value().strip():
            raise ProviderError('credentials_missing', 503)
        try:
            with httpx.Client(transport=self.transport, trust_env=False, follow_redirects=False,
                              timeout=self.settings.bitrefill_timeout_seconds) as client:
                with client.stream('GET', REST_BASE + path, headers={
                    'Authorization': 'Bearer ' + key.get_secret_value(), 'Accept': 'application/json',
                }) as response:
                    if response.status_code != 200:
                        code = {401: 'credentials_rejected', 403: 'rest_access_denied',
                                429: 'rate_limited'}.get(response.status_code, 'rest_read_failed')
                        raise ProviderError(code)
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > 1_000_000:
                            raise ProviderError('response_too_large')
                        chunks.append(chunk)
                    result = json.loads(b''.join(chunks), parse_float=Decimal)
                    if not isinstance(result, dict):
                        raise ValueError()
                    return result
        except httpx.TimeoutException:
            raise ProviderError('timeout', 504) from None
        except httpx.TransportError:
            raise ProviderError('transport_error') from None
        except (ValueError, TypeError, RecursionError):
            raise ProviderError('unsupported_response_contract') from None

    def inspect_invoice(self, invoice_id: str):
        """Whitelisted observation only. Raw provider price has NO assumed units.

        Never returns a Quote or settles a reservation. Invoice IDs are UUIDs;
        paths, query parameters, payment links and credentials cannot be supplied.
        """
        try:
            if str(UUID(invoice_id)) != invoice_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ProviderError('invalid_invoice_id') from None
        raw = self._read('/invoices/' + invoice_id)
        try:
            data = raw['data']
            if data['id'] != invoice_id:
                raise ProviderError('invoice_identity_mismatch')
            payment = data['payment']
            price = payment['price']
            if isinstance(price, bool) or not isinstance(price, (str, int, Decimal)):
                raise ValueError()
            number = Decimal(price)
            if not number.is_finite() or number < 0 or len(str(price)) > 64:
                raise ValueError()
            orders = data['orders']
            if not isinstance(orders, list) or len(orders) > 20:
                raise ValueError()
            return dict(invoice_id=invoice_id, invoice_status=bounded_string(data['status']),
                        payment_method=bounded_string(payment['method']),
                        payment_price_raw=str(price), payment_currency=bounded_string(payment['currency']),
                        payment_status=bounded_string(payment['status']),
                        orders=[dict(status=bounded_string(o['status']),
                                     product_id=bounded_string(o['product']['id']),
                                     face_value=bounded_string(str(o['product']['value'])),
                                     face_currency=bounded_string(o['product']['currency'])) for o in orders],
                        price_units_verified=False, maximum_usd_debit_verified=False,
                        checkout_blocked=True)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ProviderError('unsupported_response_contract') from None

    def assess(self):
        try:
            ping = self._read('/ping')
            if ping.get('message') != 'pong':
                raise ProviderError('unsupported_response_contract')
            balance = self._read('/accounts/balance')['data']
            currency = bounded_string(balance['currency'], 8)
            amount = balance['balance']
            if isinstance(amount, bool) or not isinstance(amount, (str, int, Decimal)):
                raise ValueError()
            numeric = Decimal(amount)
            if not numeric.is_finite() or numeric < 0:
                raise ValueError()
            product = self._read('/products/swiggy-money-india')['data']
            if product['id'] != 'swiggy-money-india' or product['currency'] != 'INR':
                raise ValueError()
            packages = [p for p in product['packages'] if p.get('value') == '50']
            if len(packages) != 1:
                raise ValueError()
            package_id = bounded_string(packages[0]['id'])
            invoices = self._read('/invoices?limit=1')['data']
            if not isinstance(invoices, list):
                raise ValueError()
            # Do not infer invoice creation permission, USD access, price units or
            # payment immutability from successful GETs or catalog price numbers.
            return dict(rest_reads_authenticated=True, rest_balance_currency=currency,
                        rest_balance_amount=str(amount), product_id=product['id'],
                        face_value='50', face_currency='INR', package_id=package_id,
                        returned_invoice_count=len(invoices), invoice_creation_verified=False,
                        maximum_debit_verified=False, checkout_blocked=True)
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            raise ProviderError('unsupported_response_contract') from None


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--invoice-id', help='Read an existing invoice UUID; never creates or pays')
    args = parser.parse_args()
    try:
        verifier = RestAccessVerifier(get_settings())
        result = verifier.inspect_invoice(args.invoice_id) if args.invoice_id else verifier.assess()
        print(json.dumps(result))
    except ProviderError as exc:
        print(f'REST read verification blocked: {exc.code}')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
