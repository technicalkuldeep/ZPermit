"""Explicit read-only live network probe and wallet-initiated tx observation.

No wallet opening, creation, synchronization, secret import or broadcasting.
"""
import argparse
import json

from app.core.config import get_settings
from app.core.database import create_database_engine
from app.core.security import Identity
from app.integrations.public_testnet import PublicTestnetClient
from app.integrations.zcash import ZcashError
from app.schemas.public_testnet import ObserveTransactionInput
from app.services.public_testnet import PublicTestnetWorkflow
from app.services.spending import DomainError


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--address', help='Public utest1 address copied from the official wallet GUI')
    p.add_argument('--txid', help='Real txid copied from wallet history; read-only lookup')
    p.add_argument('--record-key', help='Persist --txid evidence in the local ZPermit DB; requires initialized schema')
    args = p.parse_args()
    if args.record_key and not args.txid:
        p.error('--record-key requires --txid')
    settings = get_settings().model_copy(update={'zcash_public_reads_enabled': True})
    client = PublicTestnetClient(settings)
    engine = None
    try:
        print(json.dumps(client.readiness(), indent=2))
        if args.address:
            print(json.dumps(client.inspector.address(args.address), indent=2))
        if args.txid:
            if args.record_key:
                engine = create_database_engine(settings.database_url)
                result = PublicTestnetWorkflow(engine, settings, client).record(
                    ObserveTransactionInput(txid=args.txid, request_key=args.record_key),
                    Identity('owner', settings.dev_owner_id))
                print(result.model_dump_json(indent=2))
            else:
                print(json.dumps(client.transaction(args.txid), indent=2))
    except ZcashError as exc:
        print(json.dumps({'status': 'blocked', 'code': exc.code}))
        raise SystemExit(1) from None
    except DomainError as exc:
        print(json.dumps({'status': 'blocked', 'detail': exc.detail}))
        raise SystemExit(1) from None
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    main()
