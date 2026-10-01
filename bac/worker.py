import asyncio, signal
from bac.core.services import Services
from bac.agent.engine import AgentEngine


async def main():
    s = Services()
    agent = AgentEngine(s)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig, lambda: (agent.stop.set(), s.extraction_engine.stopping.set())
        )
    from bac.learning.private import PrivateFiles
    await asyncio.gather(agent.run(), s.extraction_engine.run(), PrivateFiles(s).run(agent.stop))


if __name__ == "__main__":
    asyncio.run(main())
