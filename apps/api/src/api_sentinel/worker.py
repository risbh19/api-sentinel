"""Idle process scaffold. Job storage and claiming arrive with event processing."""

import asyncio
import signal


async def main() -> None:
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stopped.set)
    print('{"service":"worker","state":"idle","job_processing":false}', flush=True)
    await stopped.wait()


if __name__ == "__main__":
    asyncio.run(main())
