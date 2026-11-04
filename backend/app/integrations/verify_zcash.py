"""Opt-in local verification tool. Default is read-only; no seed/key input.

Run from backend with the local venv. This is a trusted local owner tool, not an
HTTP authentication bypass available to agents. See docs/zcash-testnet.md.
"""
import argparse
import json
import sys
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.core.database import create_database_engine
from app.core.security import Identity
from app.integrations.zcash import ZalletAdapter, ZcashError
from app.schemas.zcash import PaymentConfirmation, PaymentInput
from app.services.spending import DomainError
from app.services.zcash import ZcashWorkflow

ACK = 'SEND TESTNET TAZ WITH AUTOMATIC ZIP317 FEE'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare', metavar='TESTNET_UNIFIED_ADDRESS')
    mode.add_argument('--evidence-payment', type=UUID, help='Read-only local node evidence for a mined payment')
    mode.add_argument('--payment', type=UUID, help='Read-only refresh of an existing payment')
    mode.add_argument('--confirm-payment', type=UUID, help='Interactive, explicit owner confirmation')
    parser.add_argument('--amount-zatoshis', type=int)
    args = parser.parse_args()
    if args.prepare and args.amount_zatoshis is None:
        parser.error('--prepare requires --amount-zatoshis')
    if args.amount_zatoshis is not None and not args.prepare:
        parser.error('--amount-zatoshis is only valid with --prepare')
    config = get_settings()
    engine = create_database_engine(config.database_url)
    wallet = ZalletAdapter(config)
    owner = Identity('owner', config.dev_owner_id)
    workflow = ZcashWorkflow(engine, config, wallet)
    try:
        if args.prepare:
            result = workflow.prepare(PaymentInput(destination=args.prepare,
                                      amount_zatoshis=args.amount_zatoshis,
                                      request_key='local-' + str(uuid4())), owner)
        elif args.evidence_payment:
            payment = workflow.get(str(args.evidence_payment), owner)
            print(json.dumps(wallet.evidence(payment.txid), indent=2))
            return
        elif args.payment:
            result = workflow.refresh(str(args.payment), owner)
        elif args.confirm_payment:
            result = workflow.get(str(args.confirm_payment), owner)
            print(result.model_dump_json(indent=2))
            if result.state != 'pending_approval':
                raise DomainError(409, 'Existing attempt: inspect status; do not create a replacement')
            if not sys.stdin.isatty():
                raise DomainError(409, 'Confirmation requires an interactive owner terminal')
            print('Owner: review destination, amount and fingerprint above.')
            print('Wallet adds an automatic ZIP317 fee; this request is not a fee-capped quote.')
            print('To dispatch this testnet payment, type exactly: ' + ACK)
            if input('Confirmation: ') != ACK:
                raise DomainError(409, 'Confirmation declined; nothing dispatched')
            result = workflow.confirm(str(args.confirm_payment),
                        PaymentConfirmation(fingerprint=result.fingerprint, confirmation=ACK), owner)
        else:
            print(json.dumps(wallet.readiness(), indent=2))
            print(json.dumps(wallet.balance(), indent=2))
            return
        print(result.model_dump_json(indent=2))
    except ZcashError as exc:
        print('Testnet verification blocked: ' + exc.code, file=sys.stderr)
        raise SystemExit(1) from None
    except DomainError as exc:
        print(exc.detail, file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
