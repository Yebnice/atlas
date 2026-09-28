from app.arbitrage import TriangleQuote, evaluate_triangle


def legs():
    return (
        ("BTCUSDT", "BUY", "BTC", "USDT"),
        ("ETHBTC", "BUY", "ETH", "BTC"),
        ("ETHUSDT", "SELL", "ETH", "USDT"),
    )


def test_triangle_profitable_after_costs():
    q={
      "BTCUSDT": TriangleQuote("BTCUSDT", 100.0, 100.1, 1000, 1000),
      "ETHBTC": TriangleQuote("ETHBTC", 0.0202, 0.0203, 1000, 1000),
      "ETHUSDT": TriangleQuote("ETHUSDT", 2.06, 2.07, 1000, 1000),
    }
    r=evaluate_triangle(q, legs(), 1000, 0.0005, 0.01, 0.01, "USDT")
    assert r.gross_edge_pct > 0
    assert r.end_quote > 0


def test_triangle_blocks_bad_price():
    q={
      "BTCUSDT":TriangleQuote("BTCUSDT",0,0),
      "ETHBTC":TriangleQuote("ETHBTC",1,1),
      "ETHUSDT":TriangleQuote("ETHUSDT",1,1),
    }
    r=evaluate_triangle(q, legs(), 100, 0.001)
    assert not r.executable
    assert r.reason == "invalid_price"


def test_triangle_blocks_broken_asset_chain():
    q={
      "BTCUSDT":TriangleQuote("BTCUSDT",100,100),
      "ETHBTC":TriangleQuote("ETHBTC",0.02,0.02),
      "ETHUSDT":TriangleQuote("ETHUSDT",2,2),
    }
    bad=(
      ("BTCUSDT","BUY","BTC","USDT"),
      ("ETHBTC","BUY","ETH","USDT"),
      ("ETHUSDT","SELL","ETH","USDT"),
    )
    r=evaluate_triangle(q,bad,100,0.001,start_asset="USDT")
    assert not r.executable
    assert r.reason == "asset_chain_mismatch"


def test_triangle_blocks_insufficient_depth():
    q={
      "BTCUSDT":TriangleQuote("BTCUSDT",100,100,0,0.5),
      "ETHBTC":TriangleQuote("ETHBTC",0.02,0.02,1000,1000),
      "ETHUSDT":TriangleQuote("ETHUSDT",2,2,1000,1000),
    }
    r=evaluate_triangle(q,legs(),100,0.001,start_asset="USDT")
    assert not r.executable
    assert r.reason == "insufficient_top_of_book_depth"
