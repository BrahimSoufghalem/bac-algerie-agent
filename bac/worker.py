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
    await asyncio.gather(agent.run(), s.extraction_engine.run())


if __name__ == "__main__":
    asyncio.run(main())
