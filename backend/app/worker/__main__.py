import logging

from app.core.db import get_engine
from app.worker.config import WorkerConfig
from app.worker.loop import Worker


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    Worker(get_engine(), WorkerConfig.from_env()).run_forever()


if __name__ == "__main__":
    main()
