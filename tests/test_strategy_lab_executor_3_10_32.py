from app.executor_engine import ExecutorConfig, ExecutorValidationError, build_executor_plan, next_slice

def test_executor_plan_slices_exactly():
    p=build_executor_plan(ExecutorConfig(kind="TWAP",total_quantity=10,slices=4,interval_seconds=60),market_price=100)
    assert p["slice_quantity"] == 2.5
    assert next_slice(p,0)["quantity"] == 2.5
    assert next_slice(p,7.5)["quantity"] == 2.5
    assert next_slice(p,10) is None

def test_executor_rejects_invalid_quantity():
    try: build_executor_plan(ExecutorConfig(kind="DCA",total_quantity=0),market_price=100)
    except ExecutorValidationError: return
    assert False

def test_executor_rejects_unknown_kind():
    try: build_executor_plan(ExecutorConfig(kind="HFT",total_quantity=1),market_price=100)
    except ExecutorValidationError: return
    assert False
