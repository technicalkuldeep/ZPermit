"""Authenticated read-only verification. Never dispatches buy-products."""
from app.core.config import get_settings
from app.integrations.bitrefill import BitrefillClient, ProviderError


def main():
    settings = get_settings()
    if not settings.bitrefill_api_key:
        print('SKIPPED: no Bitrefill credential configured')
        return
    provider = BitrefillClient(settings)
    try:
        balance = provider.balance()
        print(f'USD balance: {balance.amount_cents} cents')
        for slug, query in [('swiggy-money-india', 'Swiggy'), ('flipkart-india', 'Flipkart'),
                            ('google-play-india', 'Google Play')]:
            products = provider.search(query, 'Read-only ZPermit compatibility verification', 'IN')
            if slug not in [p.id for p in products]:
                raise ProviderError('search_identity_missing')
            product = provider.details(slug)
            quote = provider.quote(product, '50', None)
            print(f'{product.id}: face=50 {product.currency}, indicative={quote.total_cents} USD cents, '
                  f'in_stock={product.available}, balance={product.accepts_balance}, type={product.product_type}')
        print('Checkout BLOCKED: maximum_debit_unbounded. No purchase attempted; live gate unchanged.')
    except ProviderError as exc:
        print(f'Live read verification blocked: {exc.code}')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
