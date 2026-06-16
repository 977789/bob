from aiofiles.os import remove, path as aiopath
from asyncio import sleep, TimeoutError
from time import time
from aiohttp.client_exceptions import ClientError
from aioqbt.exc import AQError

from ... import (
    task_dict,
    task_dict_lock,
    intervals,
    qb_torrents,
    qb_listener_lock,
    LOGGER,
)
from ...core.config_manager import Config
from ...core.torrent_manager import TorrentManager
from ..ext_utils.bot_utils import new_task
from ..ext_utils.files_utils import clean_unwanted
from ..ext_utils.status_utils import get_readable_time, get_task_by_gid
from ..ext_utils.task_manager import stop_duplicate_check, limit_checker
from ..mirror_leech_utils.status_utils.qbit_status import QbittorrentStatus
from ..telegram_helper.message_utils import update_status_message


async def _check_speed_limit(tor_info, tag):
    """Check if download speed is below limit and handle accordingly"""
    if Config.DL_SPEED_LIMIT <= 0:
        return False  # Speed limit disabled

    current_speed = tor_info.dlspeed  # Speed in bytes/sec
    speed_limit_bytes = Config.get_speed_limit_bytes()  # Convert MB/s to bytes/s
    current_time = time()

    # Start monitoring speed after initial buffering period (30 seconds)
    if current_time - qb_torrents[tag]["start_time"] <= 30:
        return False

    if current_speed < speed_limit_bytes:
        if qb_torrents[tag]["slow_speed_start"] is None:
            qb_torrents[tag]["slow_speed_start"] = current_time
            LOGGER.warning(
                f"Speed limit warning: {tor_info.name} - Speed: {current_speed} bytes/s is below limit: {Config.DL_SPEED_LIMIT} MB/s"
            )
        elif (
            current_time - qb_torrents[tag]["slow_speed_start"]
            >= Config.SPEED_LIMIT_TIMEOUT
        ):
            from ..ext_utils.status_utils import get_readable_file_size

            speed_str = get_readable_file_size(current_speed)
            await _on_download_error(
                f"Download cancelled due to slow speed!\nCurrent: {speed_str}/s | Limit: {Config.DL_SPEED_LIMIT} MB/s",
                tor_info,
            )
            return True  # Task was cancelled
    else:
        # Reset slow speed timer if speed is above limit
        qb_torrents[tag]["slow_speed_start"] = None

    return False


async def _remove_torrent(hash_, tag):
    await TorrentManager.qbittorrent.torrents.delete([hash_], True)
    async with qb_listener_lock:
        if tag in qb_torrents:
            del qb_torrents[tag]
    await TorrentManager.qbittorrent.torrents.delete_tags([tag])


@new_task
async def _on_download_error(err, tor, button=None, is_limit=False):
    LOGGER.info(f"Cancelling Download: {tor.name}")
    ext_hash = tor.hash
    if task := await get_task_by_gid(ext_hash[:12]):
        await task.listener.on_download_error(err, button, is_limit)
    await TorrentManager.qbittorrent.torrents.stop([ext_hash])
    await sleep(0.3)
    await _remove_torrent(ext_hash, tor.tags[0])


@new_task
async def _on_seed_finish(tor):
    ext_hash = tor.hash
    LOGGER.info(f"Cancelling Seed: {tor.name}")
    if task := await get_task_by_gid(ext_hash[:12]):
        msg = f"Seeding stopped with Ratio: {round(tor.ratio, 3)} and Time: {get_readable_time(int(tor.seeding_time.total_seconds() or '0'))}"
        await task.listener.on_upload_error(msg)
    await _remove_torrent(ext_hash, tor.tags[0])


@new_task
async def _stop_duplicate(tor):
    if task := await get_task_by_gid(tor.hash[:12]):
        if task.listener.stop_duplicate:
            task.listener.name = tor.content_path.rsplit("/", 1)[-1].rsplit(".!qB", 1)[
                0
            ]
            msg, button = await stop_duplicate_check(task.listener)
            if msg:
                await _on_download_error(msg, tor, button)


@new_task
async def _size_check(tor):
    if task := await get_task_by_gid(tor.hash[:12]):
        task.listener.size = tor.size
        mmsg = await limit_checker(task.listener)
        if mmsg:
            await _on_download_error(mmsg, tor, is_limit=True)


@new_task
async def _on_download_complete(tor):
    ext_hash = tor.hash
    tag = tor.tags[0]
    if task := await get_task_by_gid(ext_hash[:12]):
        if not task.listener.seed:
            await TorrentManager.qbittorrent.torrents.stop([ext_hash])
        if task.listener.select:
            await clean_unwanted(task.listener.dir)
            path = tor.content_path.rsplit("/", 1)[0]
            res = await TorrentManager.qbittorrent.torrents.files(ext_hash)
            for f in res:
                if f.priority == 0 and await aiopath.exists(f"{path}/{f.name}"):
                    try:
                        await remove(f"{path}/{f.name}")
                    except Exception:
                        pass
        await task.listener.on_download_complete()
        if intervals["stopAll"]:
            return
        if task.listener.seed and not task.listener.is_cancelled:
            async with task_dict_lock:
                if task.listener.mid in task_dict:
                    removed = False
                    task_dict[task.listener.mid] = QbittorrentStatus(
                        task.listener, True
                    )
                else:
                    removed = True
            if removed:
                await _remove_torrent(ext_hash, tag)
                return
            async with qb_listener_lock:
                if tag in qb_torrents:
                    qb_torrents[tag]["seeding"] = True
                else:
                    return
            await update_status_message(task.listener.message.chat.id)
            LOGGER.info(f"Seeding started: {tor.name} - Hash: {ext_hash}")
        else:
            await _remove_torrent(ext_hash, tag)
    else:
        await _remove_torrent(ext_hash, tag)


@new_task
async def _qb_listener():
    while True:
        async with qb_listener_lock:
            try:
                torrents = await TorrentManager.qbittorrent.torrents.info()
                if len(torrents) == 0:
                    intervals["qb"] = ""
                    break
                for tor_info in torrents:
                    tag = tor_info.tags[0]
                    if tag not in qb_torrents:
                        continue
                    state = tor_info.state
                    if state == "metaDL":
                        qb_torrents[tag]["stalled_time"] = time()
                        if (
                            Config.TORRENT_TIMEOUT
                            and time() - qb_torrents[tag]["start_time"]
                            >= Config.TORRENT_TIMEOUT
                        ):
                            await _on_download_error("Dead Torrent!", tor_info)
                        else:
                            await TorrentManager.qbittorrent.torrents.reannounce(
                                [tor_info.hash]
                            )
                    elif state == "downloading":
                        qb_torrents[tag]["stalled_time"] = time()
                        if not qb_torrents[tag]["stop_dup_check"]:
                            qb_torrents[tag]["stop_dup_check"] = True
                            await _stop_duplicate(tor_info)
                        if not qb_torrents[tag]["size_check"]:
                            qb_torrents[tag]["size_check"] = True
                            await _size_check(tor_info)

                        # Check download speed limit
                        if await _check_speed_limit(tor_info, tag):
                            continue  # Task was cancelled due to slow speed
                    elif state == "stalledDL":
                        # Also enforce speed limit while stalled (previously only checked in 'downloading')
                        # This handles cases where torrent becomes stalled with very low/zero speed
                        try:
                            if await _check_speed_limit(tor_info, tag):
                                continue  # Cancelled due to prolonged slow speed
                        except Exception as e:
                            LOGGER.debug(
                                f"Speed limit check (stalledDL) error for {tor_info.name}: {e}"
                            )
                        if (
                            not qb_torrents[tag]["rechecked"]
                            and 0.99989999999999999 < tor_info.progress < 1
                        ):
                            msg = f"Force recheck - Name: {tor_info.name} Hash: "
                            msg += f"{tor_info.hash} Downloaded Bytes: {tor_info.downloaded} "
                            msg += f"Size: {tor_info.size} Total Size: {tor_info.total_size}"
                            LOGGER.warning(msg)
                            await TorrentManager.qbittorrent.torrents.recheck(
                                [tor_info.hash]
                            )
                            qb_torrents[tag]["rechecked"] = True
                        elif (
                            Config.TORRENT_TIMEOUT
                            and time() - qb_torrents[tag]["stalled_time"]
                            >= Config.TORRENT_TIMEOUT
                        ):
                            await _on_download_error("Dead Torrent!", tor_info)
                        else:
                            await TorrentManager.qbittorrent.torrents.reannounce(
                                [tor_info.hash]
                            )
                    elif state == "missingFiles":
                        await TorrentManager.qbittorrent.torrents.recheck(
                            [tor_info.hash]
                        )
                    elif state == "error":
                        await _on_download_error(
                            "No enough space for this torrent on device", tor_info
                        )
                    elif (
                        int(tor_info.completion_on.timestamp()) != -1
                        and not qb_torrents[tag]["uploaded"]
                        and state
                        in [
                            "queuedUP",
                            "stalledUP",
                            "uploading",
                            "forcedUP",
                        ]
                    ):
                        qb_torrents[tag]["uploaded"] = True
                        await _on_download_complete(tor_info)
                    elif (
                        state in ["stoppedUP", "stoppedDL"]
                        and qb_torrents[tag]["seeding"]
                    ):
                        qb_torrents[tag]["seeding"] = False
                        await _on_seed_finish(tor_info)
                        await sleep(0.5)
            except (ClientError, TimeoutError, Exception, AQError) as e:
                LOGGER.error(str(e))
        await sleep(3)


async def on_download_start(tag):
    async with qb_listener_lock:
        qb_torrents[tag] = {
            "start_time": time(),
            "stalled_time": time(),
            "stop_dup_check": False,
            "size_check": False,
            "rechecked": False,
            "uploaded": False,
            "seeding": False,
            "slow_speed_start": None,  # Track when speed became too slow
        }
        if not intervals["qb"]:
            intervals["qb"] = await _qb_listener()
