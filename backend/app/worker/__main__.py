import functools
import logging
import signal
from types import FrameType

from app.core.db import get_engine
from app.core.settings import get_settings
from app.services.runs import execute_run
from app.worker.config import WorkerConfig
from app.worker.loop import Worker

log = logging.getLogger("localetl.worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    worker = Worker(get_engine(), WorkerConfig.from_env())
    # should_stop makes the engine raise RunInterrupted at the next stage or chunk boundary.
    worker.executor = functools.partial(
        execute_run,
        data_dir=settings.localetl_data_dir,
        chunk_rows=settings.localetl_chunk_rows,
        should_stop=worker.stop_event.is_set,
    )

    def on_signal(signum: int, _frame: FrameType | None) -> None:
        log.info(
            "received %s: stop claiming, interrupting the active run", signal.Signals(signum).name
        )
        worker.request_stop()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    worker.run_forever()


if __name__ == "__main__":
    main()
