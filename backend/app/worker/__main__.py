import functools
import logging

from app.core.db import get_engine
from app.core.settings import get_settings
from app.services.runs import execute_run
from app.worker.config import WorkerConfig
from app.worker.loop import Worker


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    executor = functools.partial(
        execute_run, data_dir=settings.localetl_data_dir, chunk_rows=settings.localetl_chunk_rows
    )
    Worker(get_engine(), WorkerConfig.from_env(), executor=executor).run_forever()


if __name__ == "__main__":
    main()
