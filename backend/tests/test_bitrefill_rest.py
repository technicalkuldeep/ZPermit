"""Isolated REST access probes; no live requests or simulated purchase claims."""
import json

import httpx
import pytest

from app.core.config import Settings
from app.integrations.bitrefill import ProviderError
from app.integrations.verify_bitrefill_rest import READ_PATHS, RestAccessVerifier


@pytest.fixture(autouse=True)
def block_live(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Live HTTP forbidden')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', forbidden)


def config():
    return Settings(_env_file=None, BITREFILL_API_KEY='test-only-secret')


def fixtures():
    # Sanitized authenticated REST shapes, 2026-11-04. BTC is NOT USD.
    return [dict(meta={}, message='pong'), dict(data={'balance':0, 'currency':'BTC'}),
            dict(data={'id':'swiggy-money-india','currency':'INR', 'in_stock':True,
                       'packages':[{'id':'swiggy-money-india<&>50', 'value':'50', 'price':684, 'amount':50}]}),
            dict(data=[])]


def test_get_only_assessment_never_claims_checkout_support():
    calls = []
    def handle(request):
        assert request.method == 'GET'
        assert request.headers['authorization'] == 'Bearer test-only-secret'
        assert request.url.host == 'api.bitrefill.com'
        assert request.content == b''
        calls.append(request)
        return httpx.Response(200, json=fixtures()[len(calls)-1])
    result = RestAccessVerifier(config(), httpx.MockTransport(handle)).assess()
    assert len(calls) == 4
    assert result['rest_balance_currency'] == 'BTC' and result['rest_balance_amount'] == '0'
    assert result['face_currency'] == 'INR' and result['face_value'] == '50'
    assert result['package_id'] == 'swiggy-money-india<&>50'
    assert result['checkout_blocked']
    assert not result['maximum_debit_verified'] and not result['invoice_creation_verified']
    assert 'price' not in result


@pytest.mark.parametrize('path', ['/invoices','/invoices/any/pay','https://other.example/', '/accounts/balance?currency=USD'])
def test_unapproved_paths_blocked_before_transport(path):
    verifier = RestAccessVerifier(config(), httpx.MockTransport(lambda r: pytest.fail('must not dispatch')))
    with pytest.raises(ProviderError) as error:
        verifier._read(path)
    assert error.value.code == 'rest_read_not_allowed'


@pytest.mark.parametrize('status,code', [(401,'credentials_rejected'),(403,'rest_access_denied'),
                                         (429,'rate_limited'),(302,'rest_read_failed'),(500,'rest_read_failed')])
def test_errors_sanitized_no_retry_or_redirect(status, code):
    calls=[]
    def handle(request):
        calls.append(request)
        return httpx.Response(status, text='private codes and credentials', headers={'Location':'https://other.example'})
    with pytest.raises(ProviderError) as error:
        RestAccessVerifier(config(), httpx.MockTransport(handle)).assess()
    assert error.value.code == code and len(calls) == 1
    assert 'private' not in str(error.value)


def test_timeout_does_not_retry():
    calls=[]
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout('private data', request=request)
    with pytest.raises(ProviderError) as error:
        RestAccessVerifier(config(), httpx.MockTransport(handle)).assess()
    assert error.value.code == 'timeout' and len(calls) == 1


@pytest.mark.parametrize('body', [[], 'not-json', {'message':'wrong'}, {'data':{}}])
def test_bad_contract_fails_closed(body):
    with pytest.raises(ProviderError):
        RestAccessVerifier(config(), httpx.MockTransport(lambda r: httpx.Response(200, json=body))).assess()


def test_no_credentials_no_dispatch():
    with pytest.raises(ProviderError) as error:
        RestAccessVerifier(Settings(_env_file=None, BITREFILL_API_KEY=None),
                           httpx.MockTransport(lambda r: pytest.fail('no dispatch'))).assess()
    assert error.value.code == 'credentials_missing'


def test_invoice_secrets_and_account_ids_never_forwarded():
    bodies = fixtures()
    bodies[3] = {'data':[{'id':'private-id', 'redemption_info':{'code':'PRIVATE-CODE'},
                          'user':{'email':'PRIVATE-EMAIL'}, 'invoice_access_token':'PRIVATE-TOKEN'}]}
    responses = iter(bodies)
    result = RestAccessVerifier(config(), httpx.MockTransport(lambda r: httpx.Response(200, json=next(responses)))).assess()
    assert result['returned_invoice_count'] == 1
    assert 'PRIVATE' not in json.dumps(result) and 'private-id' not in json.dumps(result)


INVOICE_ID = '1f81dedb-ea5d-4065-9332-81d573e98f3a'


def invoice_fixture():
    return {'data': {'id': INVOICE_ID, 'status':'not_delivered',
            'payment':{'method':'balance','currency':'BTC','price':682,'status':'unpaid'},
            'orders':[{'status':'created','product':{'id':'swiggy-money-india','value':'50','currency':'INR'},
                       'redemption_info':{'code':'PRIVATE'}}],
            'user':{'email':'PRIVATE'}, 'invoice_access_token':'PRIVATE'}}


def test_existing_invoice_read_does_not_convert_btc_or_fulfill():
    def handle(request):
        assert request.method == 'GET'
        assert request.url.path == '/v2/invoices/' + INVOICE_ID
        return httpx.Response(200, json=invoice_fixture())
    result = RestAccessVerifier(config(), httpx.MockTransport(handle)).inspect_invoice(INVOICE_ID)
    assert result['payment_price_raw'] == '682' and result['payment_currency'] == 'BTC'
    assert result['payment_status'] == 'unpaid' and result['invoice_status'] == 'not_delivered'
    assert result['orders'][0]['face_currency'] == 'INR'
    assert not result['price_units_verified'] and not result['maximum_usd_debit_verified']
    assert result['checkout_blocked'] and 'PRIVATE' not in json.dumps(result)
    assert 'amount_cents' not in result


@pytest.mark.parametrize('invoice_id', [INVOICE_ID+'/pay', '../invoices', INVOICE_ID+'?currency=USD',
                                       'https://other.example', 'invalid'])
def test_invoice_read_rejects_non_uuid_before_network(invoice_id):
    with pytest.raises(ProviderError):
        RestAccessVerifier(config(), httpx.MockTransport(lambda r: pytest.fail('must not dispatch'))).inspect_invoice(invoice_id)


@pytest.mark.parametrize('price', [True, 'NaN', '-1', {}, None])
def test_invalid_raw_invoice_amounts_fail_closed(price):
    raw = invoice_fixture()
    raw['data']['payment']['price'] = price
    with pytest.raises(ProviderError):
        RestAccessVerifier(config(), httpx.MockTransport(lambda r: httpx.Response(200,json=raw))).inspect_invoice(INVOICE_ID)


def test_invoice_identity_mismatch_is_rejected():
    raw = invoice_fixture()
    raw['data']['id'] = 'other'
    with pytest.raises(ProviderError) as error:
        RestAccessVerifier(config(), httpx.MockTransport(lambda r: httpx.Response(200,json=raw))).inspect_invoice(INVOICE_ID)
    assert error.value.code == 'invoice_identity_mismatch'
