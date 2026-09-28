from __future__ import annotations

import asyncio
import signal

from .main import startup, shutdown


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await startup()
    try:
        await stop.wait()
    finally:
        await shutdown()


if __name__ == "__main__":
    asyncio.run(main())
