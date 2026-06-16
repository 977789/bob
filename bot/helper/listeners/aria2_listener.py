from aiofiles.os import remove, path as aiopath
from asyncio import sleep, TimeoutError
from time import time
from contextlib import suppress
from aiohttp.client_exceptions import ClientError
from aioaria2.exceptions import Aria2rpcException

from ... import task_dict_lock, task_dict, LOGGER, intervals
from ...core.config_manager import Config
from ...core.torrent_manager import TorrentManager, is_metadata, aria2_name
from ..ext_utils.bot_utils import bt_selection_buttons
from ..ext_utils.files_utils import clean_unwanted
from ..ext_utils.status_utils import get_task_by_gid
from ..ext_utils.task_manager import stop_duplicate_check, limit_checker
from ..mirror_leech_utils.status_utils.aria2_status import Aria2Status
from ..telegram_helper.message_utils import (
    send_message,
    delete_message,
    update_status_message,
)


async def _on_download_started(api, data):
    gid = data["params"][0]["gid"]
    with suppress(TimeoutError, ClientError, Exception):
        download, options = await api.tellStatus(gid), await api.getOption(gid)
        if options.get("follow-torrent", "") == "false":
            return
    if is_metadata(download):
        LOGGER.info(f"onDownloadStarted: {gid} METADATA")
        await sleep(1)
        if task := await get_task_by_gid(gid):
            task.listener.is_torrent = True
            if task.listener.select:
                metamsg = "Downloading Metadata, wait then you can select files. Use torrent file to avoid this wait."
                meta = await send_message(task.listener.message, metamsg)
                while True:
                    await sleep(0.5)
                    if download.get("status", "") == "removed" or download.get(
                        "followedBy", []
                    ):
                        await delete_message(meta)
                        break
                    download = await api.tellStatus(gid)
        return
    else:
        LOGGER.info(f"onDownloadStarted: {aria2_name(download)} - Gid: {gid}")
        await sleep(1)

    await sleep(2)
    if task := await get_task_by_gid(gid):
        download = await api.tellStatus(gid)
        if "bittorrent" in download:
            task.listener.is_torrent = True

        # The following line was removed to prevent overwriting the original filename
        # with a sanitized one from Aria2.
        # task.listener.name = aria2_name(download)

        msg, button = await stop_duplicate_check(task.listener)
        if msg:
            await TorrentManager.aria2_remove(download)
            await task.listener.on_download_error(msg, button)
            return


async def _on_download_complete(api, data):
    gid = data["params"][0]["gid"]
    download = None
    try:
        download, options = await api.tellStatus(gid), await api.getOption(gid)
        if options.get("follow-torrent", "") == "false":
            return
    except Aria2rpcException as e:
        if "GID" in str(e) and "not found" in str(e).lower():
            LOGGER.warning(
                f"onDownloadComplete: GID {gid} not found by tellStatus. Presuming already processed by Aria2. Clearing task."
            )
            if task := await get_task_by_gid(gid):
                await task.listener.on_download_complete()
                if intervals["stopAll"]:
                    return
                # Directly remove from history as Aria2 already processed it
                await TorrentManager.aria2.removeDownloadResult(gid)
            return
        else:
            LOGGER.error(f"onDownloadComplete: Aria2RpcException: {e} for GID {gid}")
            return
    except (TimeoutError, ClientError, Exception) as e:
        LOGGER.error(f"onDownloadComplete: {e} for GID {gid}")
        return

    if (
        not download
    ):  # Should not happen if exception handling is correct, but as a safeguard
        LOGGER.error(
            f"onDownloadComplete: Failed to get download details for GID {gid} and no specific GID not found error."
        )
        if task := await get_task_by_gid(gid):  # Attempt to cleanup task status
            await task.listener.on_download_error(
                f"Failed to get download details from Aria2 for GID {gid}"
            )
        return

    if download.get("followedBy", []):
        new_gid = download.get("followedBy", [])[0]
        LOGGER.info(f"Gid changed from {gid} to {new_gid}")
        if task := await get_task_by_gid(new_gid):
            task.listener.is_torrent = True
            if Config.BASE_URL and task.listener.select:
                if not task.queued:
                    await api.forcePause(new_gid)
                SBUTTONS = bt_selection_buttons(new_gid)
                msg = "Download paused. Choose files then press Done Selecting button to start downloading."
                await send_message(task.listener.message, msg, SBUTTONS)
    elif "bittorrent" in download:
        # This case should ideally be handled by _on_bt_download_complete for torrents.
        # If a torrent download somehow triggers _on_download_complete, this logic will run.
        LOGGER.info(
            f"onDownloadComplete: Bittorrent download {aria2_name(download)} GID: {gid} completed."
        )
        if task := await get_task_by_gid(gid):
            task.listener.is_torrent = True  # Ensure is_torrent is set
            if (
                hasattr(task, "seeding") and task.seeding
            ):  # This part might be redundant if _on_bt_download_complete handles seeding
                LOGGER.info(
                    f"Cancelling Seed: {aria2_name(download)} onDownloadComplete"
                )
                await TorrentManager.aria2_remove(
                    download
                )  # Uses the full download object
                await task.listener.on_upload_error(
                    f"Seeding stopped with Ratio: {task.ratio()} and Time: {task.seeding_time()}"
                )
            else:
                # If not seeding, or seeding not applicable here, ensure it's completed and removed
                await task.listener.on_download_complete()
                if intervals["stopAll"]:
                    return
                await TorrentManager.aria2_remove(
                    download
                )  # Uses the full download object
    else:  # Direct downloads
        LOGGER.info(f"onDownloadComplete: {aria2_name(download)} - Gid: {gid}")
        if task := await get_task_by_gid(gid):
            await task.listener.on_download_complete()
            if intervals["stopAll"]:
                return
            await TorrentManager.aria2_remove(download)  # Uses the full download object


async def _on_bt_download_complete(api, data):
    gid = data["params"][0]["gid"]
    await sleep(1)  # Short delay to allow Aria2 to finalize status

    download = None
    task_name_for_log = (
        f"GID {gid}"  # Fallback name for logging if tellStatus fails early
    )

    try:
        download = await api.tellStatus(gid)
        task_name_for_log = aria2_name(download) if download else f"GID {gid}"
    except Aria2rpcException as e:
        if "GID" in str(e) and "not found" in str(e).lower():
            LOGGER.warning(
                f"onBtDownloadComplete: GID {gid} not found by initial tellStatus. Presuming already processed. Clearing task."
            )
            if task := await get_task_by_gid(gid):
                task.listener.is_torrent = True  # Mark as torrent
                await task.listener.on_download_complete()
                if intervals["stopAll"]:
                    return
                await TorrentManager.aria2.removeDownloadResult(gid)
            return
        else:
            LOGGER.error(
                f"onBtDownloadComplete: Aria2RpcException on initial tellStatus: {e} for GID {gid}"
            )
            if task := await get_task_by_gid(gid):  # Attempt to cleanup task status
                await task.listener.on_download_error(
                    f"Aria2 error on BT complete for GID {gid}: {e}"
                )
            return
    except (TimeoutError, ClientError, Exception) as e:
        LOGGER.error(
            f"onBtDownloadComplete: Error on initial tellStatus: {e} for GID {gid}"
        )
        if task := await get_task_by_gid(gid):  # Attempt to cleanup task status
            await task.listener.on_download_error(
                f"Error getting BT status for GID {gid}: {e}"
            )
        return

    if not download:
        LOGGER.error(
            f"onBtDownloadComplete: Failed to get download details for {task_name_for_log} and no specific GID not found error."
        )
        if task := await get_task_by_gid(gid):
            await task.listener.on_download_error(
                f"Failed to get BT download details from Aria2 for {task_name_for_log}"
            )
        return

    LOGGER.info(f"onBtDownloadComplete: {task_name_for_log} - Gid: {gid}")
    if task := await get_task_by_gid(gid):
        task.listener.is_torrent = True
        if task.listener.select:
            res = download.get("files", [])
            for file_o in res:
                f_path = file_o.get("path", "")
                if file_o.get("selected", "") != "true" and await aiopath.exists(
                    f_path
                ):
                    with suppress(Exception):
                        await remove(f_path)
            await clean_unwanted(download.get("dir", ""))

        task.listener.size = int(download.get("totalLength", "0"))
        mmsg = await limit_checker(task.listener)
        if mmsg:
            await TorrentManager.aria2_remove(download)
            await task.listener.on_download_error(mmsg, is_limit=True)
            return

        if (
            task.listener.seed and not task.listener.is_cancelled
        ):  # Check is_cancelled before trying to seed
            try:
                await api.changeOption(gid, {"max-upload-limit": "0"})
            except Exception as e:  # Catch broad exception as changeOption can also fail if GID is gone
                LOGGER.error(
                    f"onBtDownloadComplete: Failed to set max-upload-limit for seeding {task_name_for_log} (GID: {gid}). Error: {e}. May already be removed by Aria2."
                )
                # Don't return yet, proceed to on_download_complete and attempt cleanup
        else:  # Not seeding or cancelled
            try:
                await api.forcePause(gid)
            except Aria2rpcException as e:
                if "GID" in str(e) and "not found" in str(e).lower():
                    LOGGER.warning(
                        f"onBtDownloadComplete: GID {gid} not found on forcePause for {task_name_for_log}. Already removed by Aria2."
                    )
                else:
                    LOGGER.error(
                        f"onBtDownloadComplete: Aria2rpcException on forcePause for {task_name_for_log} (GID: {gid}): {e}"
                    )
            except (TimeoutError, ClientError, Exception) as e:
                LOGGER.error(
                    f"onBtDownloadComplete: Error on forcePause for {task_name_for_log} (GID: {gid}): {e}"
                )

        await task.listener.on_download_complete()  # Notify bot about completion

        if intervals["stopAll"]:
            return

        # Re-check status for seeding logic or final removal
        # This is the part that was causing multiple GID NOT FOUND errors in the original log
        current_download_state = None
        try:
            current_download_state = await api.tellStatus(gid)
        except Aria2rpcException as e:
            if "GID" in str(e) and "not found" in str(e).lower():
                LOGGER.warning(
                    f"onBtDownloadComplete: GID {gid} not found on second tellStatus for {task_name_for_log}. Assuming processed."
                )
                # Task already marked complete, just ensure Aria2 history is cleared
                await TorrentManager.aria2.removeDownloadResult(gid)
                return  # Exit as GID is gone
            else:
                LOGGER.error(
                    f"onBtDownloadComplete: Aria2rpcException on second tellStatus for {task_name_for_log} (GID: {gid}): {e}"
                )
                # Proceed to attempt generic removal if possible, or it will be handled by no current_download_state
        except (TimeoutError, ClientError, Exception) as e:
            LOGGER.error(
                f"onBtDownloadComplete: Error on second tellStatus for {task_name_for_log} (GID: {gid}): {e}"
            )
            # Proceed to attempt generic removal

        if not current_download_state:
            # If second tellStatus failed (e.g. GID not found or other error),
            # and we haven't returned yet, attempt to remove by GID.
            LOGGER.info(
                f"onBtDownloadComplete: No current download state for {task_name_for_log} (GID: {gid}) after completion. Attempting removal by GID."
            )
            await TorrentManager.aria2.removeDownloadResult(
                gid
            )  # Safest bet if state is unknown but task was completed
            return

        # If we have current_download_state (meaning second tellStatus succeeded)
        if (
            task.listener.seed
            and not task.listener.is_cancelled  # Re-check is_cancelled
            and current_download_state.get("status")
            == "complete"  # Aria2 reports 'complete' for stopped seeds
            and await get_task_by_gid(
                gid
            )  # Check if task still exists in bot's context
        ):
            # This branch is for when seeding is enabled, task is 'complete' (could be paused post-download),
            # and we need to decide if it should transition to seeding state or be removed.
            # If it's truly finished and not meant to seed further (e.g. ratio/time limit met, handled by Aria2Status),
            # it would be removed by Aria2Status logic.
            # If it's just completed download and should start seeding:
            async with task_dict_lock:
                if task.listener.mid not in task_dict:  # Task removed by other means
                    await TorrentManager.aria2_remove(
                        current_download_state
                    )  # Use the state we have
                    return
                # Update task to reflect seeding status
                task_dict[task.listener.mid] = Aria2Status(
                    task.listener, gid, True
                )  # True for is_seeding
                task_dict[
                    task.listener.mid
                ].start_time = time()  # Reset start time for seeding duration
            LOGGER.info(
                f"Seeding started/confirmed for: {aria2_name(current_download_state)} - Gid: {gid}"
            )
            await update_status_message(task.listener.message.chat.id)
        elif (
            task.listener.seed
            and not task.listener.is_cancelled
            and current_download_state.get("status")
            == "paused"  # Typically what forcePause would do
            and await get_task_by_gid(gid)
        ):
            # This handles the case where we paused it (because seed was false or it was cancelled), then decided to seed.
            # Or if it was paused by user and then unpaused into seeding.
            # Essentially, if it's paused but should be seeding, transition it.
            async with task_dict_lock:
                if task.listener.mid not in task_dict:
                    await TorrentManager.aria2_remove(current_download_state)
                    return
                task_dict[task.listener.mid] = Aria2Status(task.listener, gid, True)
                task_dict[task.listener.mid].start_time = time()
            LOGGER.info(
                f"Resuming/Starting seed for paused download: {aria2_name(current_download_state)} - Gid: {gid}"
            )
            # Here, we might need to unpause it in aria2 if changeOption for max-upload-limit didn't do that.
            # However, Aria2Status itself might handle unpausing when it updates.
            # For now, just updating bot status.
            await update_status_message(task.listener.message.chat.id)

        else:  # Not seeding, or cancelled, or task no longer in bot's context
            LOGGER.info(
                f"onBtDownloadComplete: No active seeding required or task gone for {aria2_name(current_download_state)} (GID: {gid}). Removing from Aria2."
            )
            await TorrentManager.aria2_remove(
                current_download_state
            )  # Use the state we have
    else:  # Task not found by get_task_by_gid(gid) initially
        LOGGER.warning(
            f"onBtDownloadComplete: Task not found for GID {gid} after initial checks. Attempting to remove from Aria2 history."
        )
        if download:  # If we got download info before finding no task
            await TorrentManager.aria2_remove(download)
        else:  # No download info and no task, just try to remove GID from history
            await TorrentManager.aria2.removeDownloadResult(gid)


async def _on_download_stopped(_, data):
    gid = data["params"][0]["gid"]
    await sleep(4)
    if task := await get_task_by_gid(gid):
        await task.listener.on_download_error("Dead torrent!")


async def _on_download_error(api, data):
    gid = data["params"][0]["gid"]
    await sleep(1)
    LOGGER.info(f"onDownloadError: {gid}")
    error = "None"
    with suppress(TimeoutError, ClientError, Exception):
        download, options = await api.tellStatus(gid), await api.getOption(gid)
        error = download.get("errorMessage", "")
        LOGGER.info(f"Download Error: {error}")
        if options.get("follow-torrent", "") == "false":
            return
    if task := await get_task_by_gid(gid):
        await task.listener.on_download_error(error)


def add_aria2_callbacks():
    TorrentManager.aria2.onBtDownloadComplete(_on_bt_download_complete)
    TorrentManager.aria2.onDownloadComplete(_on_download_complete)
    TorrentManager.aria2.onDownloadError(_on_download_error)
    TorrentManager.aria2.onDownloadStart(_on_download_started)
    TorrentManager.aria2.onDownloadStop(_on_download_stopped)
