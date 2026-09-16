"""Owned subprocesses: cancellation and timeout terminate the entire process group."""
import asyncio
import os
import signal
import subprocess
from pathlib import Path
from typing import Optional


class ProcessOutputLimit(RuntimeError):
    pass


async def run_process(cmd: list[str], cwd: Optional[Path] = None, timeout: float = 60,
                      input_data: Optional[str] = None, env: Optional[dict] = None,
                      max_output_bytes: int = 2 * 1024 * 1024):
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(cwd) if cwd else None, env=env,
        stdin=asyncio.subprocess.PIPE if input_data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name == "posix",
    )

    async def terminate():
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                if os.name == "posix":
                    os.killpg(proc.pid, sig)
                elif proc.returncode is None:
                    proc.terminate() if sig == signal.SIGTERM else proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), 0.5)
                # Kill remaining descendants even if the group leader exited first.
                if os.name == "posix":
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                return
            except asyncio.TimeoutError:
                continue
        await proc.wait()

    async def read(stream):
        chunks, size = [], 0
        while chunk := await stream.read(65536):
            size += len(chunk)
            if size > max_output_bytes:
                raise ProcessOutputLimit("Process output exceeded the safe capture limit")
            chunks.append(chunk)
        return b"".join(chunks)

    async def write():
        if proc.stdin:
            try:
                proc.stdin.write(input_data.encode())
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                proc.stdin.close()

    readers = [asyncio.create_task(read(proc.stdout)), asyncio.create_task(read(proc.stderr)), asyncio.create_task(write())]
    async def collect():
        stdout, stderr, _ = await asyncio.gather(*readers)
        await proc.wait()
        return stdout, stderr

    try:
        stdout, stderr = await asyncio.wait_for(collect(), timeout)
        return subprocess.CompletedProcess(cmd, proc.returncode,
            stdout.decode(errors="replace"), stderr.decode(errors="replace"))
    except (asyncio.TimeoutError, asyncio.CancelledError, ProcessOutputLimit):
        cleanup = asyncio.create_task(terminate())
        cancelled_during_cleanup = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled_during_cleanup = True
        await cleanup
        if cancelled_during_cleanup:
            raise asyncio.CancelledError
        raise
    finally:
        for task in readers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
