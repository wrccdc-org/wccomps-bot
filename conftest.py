"""Root conftest: applied to all xdist workers before any tests run."""

import asyncio
import asyncio.events as events
import asyncio.runners
import functools

import nest_asyncio

# Allow nested event loops so discord.py's asyncio.Runner
# doesn't conflict with pytest-asyncio under xdist workers.
nest_asyncio.apply()

# nest_asyncio doesn't patch asyncio.Runner.run(), so we do it here.
# Remove the "cannot be called from a running event loop" guard
# to allow discord.py Bot fixtures to work under pytest-asyncio + xdist.
_original_runner_run = asyncio.Runner.run


@functools.wraps(_original_runner_run)
def _patched_runner_run(self, coro, *, context=None):
    running_loop = events._get_running_loop()
    if running_loop is not None:
        # Instead of raising, run the coroutine on the existing loop
        return running_loop.run_until_complete(coro)
    return _original_runner_run(self, coro, context=context)


asyncio.Runner.run = _patched_runner_run
