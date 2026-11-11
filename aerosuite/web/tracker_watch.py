"""The server's run-matrix writer: an asyncio task that, every few seconds, looks whether a linked sheet that writes
automatically may have something new (its projects' job records, the workbook or Excel's lock file changed) and then
writes it, as the Run matrix page's Write button does. A link is first only looked at: what changes after that is
written, so linking a sheet never writes it before you have seen its preview."""
import asyncio
import logging
from typing import Optional

from ..engine.errors import AeroSuiteError
from ..engine.tracker_links import apply_queued, link_stamp, saved_links, write_link

log = logging.getLogger("aerosuite.tracker")
INTERVAL = 20.0  # seconds between looks


class TrackerWatch:
    def __init__(self) -> None:
        self._seen: dict[str, tuple] = {}  # link id -> its stamp when last looked at
        self._task: Optional[asyncio.Task] = None

    async def check_once(self) -> int:
        """Write every automatic link whose stamp changed since the last look; returns how many were written."""
        every = saved_links()  # an unreadable file: the Run matrix page says so
        for link in every:  # hand edits queued while a workbook was open: written once it is closed
            try:
                await asyncio.to_thread(apply_queued, link)
            except (AeroSuiteError, OSError):
                pass  # logged in the link's write log
        links = [link for link in every if link.auto]
        ids = {link.id for link in links}
        self._seen = {link_id: stamp for link_id, stamp in self._seen.items() if link_id in ids}
        written = 0
        for link in links:
            stamp = await asyncio.to_thread(link_stamp, link)
            before, self._seen[link.id] = self._seen.get(link.id), stamp
            if before is None or before == stamp:
                continue
            try:
                if await asyncio.to_thread(write_link, link, (), "auto"):
                    written += 1
            except (AeroSuiteError, OSError):
                pass  # logged in the link's write log (open in Excel: tried again when the lock file goes)
            self._seen[link.id] = await asyncio.to_thread(link_stamp, link)  # its own write is not a change
        return written

    async def run_forever(self) -> None:
        while True:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # never let a look take the loop (or the server) down
                log.exception("Run-matrix check failed")
            await asyncio.sleep(INTERVAL)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self.run_forever())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


TRACKER_WATCH = TrackerWatch()
