"""Optional read-only check: python -m app.integrations.verify_bitrefill.

Never invokes checkout, even when the live flag is enabled. Prints only counts
and a product ID, not credentials or raw provider content.
"""
from app.core.config import get_settings
from app.integrations.bitrefill import BitrefillClient, ProviderError


def main():
    settings = get_settings()
    if not settings.bitrefill_api_key or not settings.bitrefill_api_key.get_secret_value().strip():
        print('SKIPPED: no Bitrefill credential configured; no live calls made')
        return
    provider = BitrefillClient(settings)
    try:
        products = provider.search('Amazon', 'Read-only integration verification; do not purchase', 'US')
        print(f'Live search returned {len(products)} products')
        if not products:
            raise ProviderError('empty_catalog')
        product = provider.details(products[0].id)
        print(f'Live details: id={product.id}, denominations={len(product.denominations)}')
        print('Read-only checks passed; checkout has NOT been verified or invoked')
    except ProviderError as exc:
        print(f'Live read verification blocked: {exc.code}')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
