import asyncio, signal
from bac.core.services import Services
from bac.agent.engine import AgentEngine


async def main():
    s = Services()
    agent = AgentEngine(s)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig, agent.stop.set
        )
    from bac.learning.private import PrivateFiles
    from bac.ops.lifecycle import MailWorker

    try:
        await asyncio.gather(
            agent.run(),
            PrivateFiles(s).run(agent.stop),
            MailWorker(s).run(agent.stop),
        )
    finally:
        s.close()


if __name__ == "__main__":
    asyncio.run(main())
