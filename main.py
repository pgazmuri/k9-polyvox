import asyncio
import logging
import os

# Set before importing anything pygame-related
# os.environ["SDL_AUDIODRIVER"] = "alsa"
# os.environ["AUDIODEV"] = "hw:0,0"

from robot_core import RobotCore


LOGGER = logging.getLogger("main")


async def main() -> None:
    core = RobotCore()
    await core.run()


if __name__ == "__main__":
    log_level = os.environ.get("K9_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    try:
        LOGGER.info("Starting RobotCore main loop")
        asyncio.run(main())
        LOGGER.info("RobotCore main loop completed")
    except KeyboardInterrupt:
        LOGGER.warning("KeyboardInterrupt caught at top level. Exiting.")
    except Exception:
        LOGGER.exception("Unhandled exception in top-level main")
        raise
    finally:
        LOGGER.info("Program exited.")
