from decimal import Decimal
from app.tron_sweep import build_sweep_intent, usdt_to_raw, SweepError


def test_usdt_raw_precision():
    assert usdt_to_raw(Decimal('12.345678')) == 12345678


def test_reject_more_than_six_decimals():
    try:
        usdt_to_raw(Decimal('1.0000001'))
    except SweepError:
        return
    assert False


def test_sweep_intent_is_deterministic():
    a = build_sweep_intent(wallet_id=7, source_address='TSource', amount_usdt='10.25', treasury_address='TTreasury')
    b = build_sweep_intent(wallet_id=7, source_address='TSource', amount_usdt='10.25', treasury_address='TTreasury')
    assert a.idempotency_key == b.idempotency_key
    assert a.raw_amount == 10250000


def test_sweep_rejects_source_treasury_same():
    try:
        build_sweep_intent(wallet_id=7, source_address='TSame', amount_usdt='1', treasury_address='TSame')
    except SweepError:
        return
    assert False

from app.tron_sweep import classify_solidified_sweep


def test_solidified_sweep_success_with_transfer_event():
    import pytest
    pytest.importorskip("bip_utils")
    source = 'TSource'
    treasury = 'TTreasury'
    # Use known valid TRON addresses for ABI topic conversion in this unit test.
    source = 'TWFuigmmGbb5gsTS4KUtY5v2FmA1rJ3yC5'
    treasury = 'T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb'
    # Event topic is fixed by ERC/TRC-20 Transfer(address,address,uint256).
    from_topic = '0' * 24 + '41' + '00' * 19 + '01'
    to_topic = '0' * 24 + '41' + '00' * 19 + '02'
    # Replace topic addresses with deterministic encodings derived from the actual addresses.
    def addr_topic(addr):
        import hashlib
        alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        n=0
        for ch in addr:
            n=n*58+alphabet.index(ch)
        raw=(n.to_bytes(25,'big'))[:-4]
        return ('00'*12 + raw[1:].hex()).rjust(64,'0')
    receipt = {'id':'a'*64,'result':'SUCCESS','receipt':{'result':'SUCCESS'},'log':[{'address':'41'+'00'*20,'topics':['ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a9df523b3ef',addr_topic(source),addr_topic(treasury)],'data':hex(1000000)[2:].rjust(64,'0')}]}
    # Contract address must match the event; use the configured USDT contract.
    receipt['log'][0]['address']='41'+'11'*20
    tx={'txID':'a'*64,'ret':[{'contractRet':'SUCCESS'}]}
    status,evidence=classify_solidified_sweep(tx_body=tx,receipt=receipt,transaction_id='a'*64,source=source,treasury=treasury,contract='41'+'11'*20,expected_raw_amount=1000000)
    assert status == 'SETTLED'
    assert evidence['observed_raw'] == 1000000


def test_solidified_sweep_missing_receipt_is_pending():
    status,_=classify_solidified_sweep(tx_body={},receipt={},transaction_id='a'*64,source='TSource',treasury='TTreasury',contract='41'+'11'*20,expected_raw_amount=1)
    assert status == 'PENDING_CONFIRMATION'
