import asyncio
import ast
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.deriv import DerivBroker, DerivConfig, DerivError


def test_deriv_live_requires_account_id():
    try:
        DerivBroker(DerivConfig(123, 'x'*24, live=True))
    except DerivError as exc:
        assert 'account ID' in str(exc)
    else:
        raise AssertionError('live Deriv broker accepted missing account ID')


def test_deriv_uses_current_otp_account_path():
    b = DerivBroker(DerivConfig(123, 'x'*24, 'CR123'))
    assert b.config.otp_endpoint.endswith('/trading/v1/options/accounts')


def test_main_has_customer_scoped_deriv_routes_without_duplicates():
    source = Path(__file__).parents[1] / 'app' / 'main.py'
    tree = ast.parse(source.read_text())
    routes=[]
    for n in ast.walk(tree):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and isinstance(d.func.value,ast.Name) and d.func.value.id=='app' and d.args and isinstance(d.args[0],ast.Constant):
                    routes.append((d.func.attr,d.args[0].value))
    assert ('post','/api/customer/broker/deriv/connect') in routes
    assert ('post','/api/customer/deriv/preflight') in routes
    assert ('post','/api/customer/deriv/execute') in routes
    assert len(routes) == len(set(routes))
