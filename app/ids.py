import hashlib


def make_signal_id(exchange: str, symbol: str, timeframe: str, signal_timestamp: str,
                   side: str, strategy: str = "lightgbm-wf-v1") -> str:
    return "|".join([strategy, exchange, symbol, timeframe, signal_timestamp, side])


def client_order_id(signal_id: str) -> str:
    return "ait-" + hashlib.sha256(signal_id.encode()).hexdigest()[:24]
