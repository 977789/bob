from pyrogram.handlers import CallbackQueryHandler
from pyrogram.filters import regex

from .. import LOGGER
from ..helper.mirror_leech_utils.download_utils.direct_downloader import (
    add_direct_download,
)
from ..helper.mirror_leech_utils.download_utils.direct_link_generator import (
    safe_int_size,
)
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    send_message,
    edit_message,
    delete_message,
)
from ..helper.ext_utils.status_utils import get_readable_file_size

DIRECT_SELECT_SESS = {}
MAX_PER_PAGE = 28


def _format_caption(
    details, selected=None, page: int = 0, page_size: int = MAX_PER_PAGE
):
    title = details.get("title") or "Folder"
    lines = [
        "<b>Please select files to download from this folder!</b>",
        f"\n<blockquote><b>Folder:</b> <code>{title}</code></blockquote>",
    ]

    contents = details.get("contents", [])
    total = len(contents)

    # Calculate selected vs total size and count
    if selected is not None:
        selected_count = len(selected)
        total_selected_size = 0
        total_all_size = 0

        for i, item in enumerate(contents, start=1):
            size = item.get("size", 0)
            size_val = safe_int_size(size)
            total_all_size += size_val
            if i in selected:
                total_selected_size += size_val

        selected_size_txt = (
            get_readable_file_size(total_selected_size)
            if total_selected_size > 0
            else "0 B"
        )
        total_size_txt = (
            get_readable_file_size(total_all_size) if total_all_size > 0 else "Unknown"
        )

        lines.extend(
            [
                f"\n<b>📊 Selection Info:</b>",
                f"├ <b>Files:</b> <code>{selected_count}/{total}</code>",
                f"╰ <b>Size:</b> <code>{selected_size_txt}/{total_size_txt}</code>",
                "\n<b><u>File List:</u></b>",
            ]
        )
    else:
        lines.append("\n<b><u>File List:</u></b>")

    if page_size <= 0:
        page_size = MAX_PER_PAGE
    pages = (total + page_size - 1) // page_size if total else 1
    start = page * page_size
    if start >= total and total > 0:
        page = max(pages - 1, 0)
        start = page * page_size
    end = min(start + page_size, total)

    for i, item in enumerate(contents[start:end], start=1):
        gidx = start + i
        name = item.get("filename", "-")
        size = item.get("size")

        # Handle various size formats for display
        size_val = safe_int_size(size)
        size_txt = get_readable_file_size(size_val) if size_val > 0 else "Unknown"

        if selected is not None and gidx not in selected:
            name = f"<s>{name}</s>"
        lines.append(f"<b>{i:02d}.</b> {name} [<code>{size_txt}</code>]")
    return "\n".join(lines)


def _build_buttons(
    selected_idx: set[int], total: int, sel_msg_id: int, page: int, page_size: int
):
    buttons = ButtonMaker()
    if page_size <= 0:
        page_size = MAX_PER_PAGE
    start = page * page_size + 1
    end = min(start + page_size - 1, total)
    pages = (total + page_size - 1) // page_size if total else 1

    # Selection number buttons
    local = 1
    for gi in range(start, end + 1):
        key = f"{local} ✅" if gi in selected_idx else f"{local}"
        buttons.data_button(key, f"dsel tgl {sel_msg_id} {gi}")
        local += 1

    # Navigation buttons for pagination
    if pages > 1:
        # Pad remaining columns to start a new row under index buttons
        count = end - start + 1
        rem = count % 4
        if rem != 0:
            for _ in range(4 - rem):
                buttons.data_button("・", f"dsel page curr {sel_msg_id}")

        # Place navigation under index buttons (in body section)
        buttons.data_button("◀ Prev", f"dsel page prev {sel_msg_id}", position="f_body")
        buttons.data_button(
            f"📄 {page + 1}/{pages}", f"dsel page curr {sel_msg_id}", position="f_body"
        )
        buttons.data_button("Next ▶", f"dsel page next {sel_msg_id}", position="f_body")

    # Footer action buttons with better organization
    buttons.data_button("Select All", f"dsel all {sel_msg_id}", position="footer")
    buttons.data_button("Clear All", f"dsel none {sel_msg_id}", position="footer")
    buttons.data_button("Cancel", f"dsel cancel {sel_msg_id}", position="footer")
    buttons.data_button("Start", f"dsel start {sel_msg_id}", position="footer")
    return buttons.build_menu(b_cols=4, h_cols=3, fb_cols=3, f_cols=2)


async def start_direct_select(listener, details: dict, path: str):
    contents = details.get("contents", [])
    if not contents or len(contents) <= 1:
        return False
    selected = set(range(1, len(contents) + 1))
    page = 0
    page_size = MAX_PER_PAGE
    caption = _format_caption(details, selected, page, page_size)
    markup = _build_buttons(
        selected, len(contents), listener.message.id, page, page_size
    )
    sel_msg = await send_message(listener.message, caption, markup)
    DIRECT_SELECT_SESS[sel_msg.id] = {
        "listener": listener,
        "details": details,
        "selected": selected,
        "path": path,
        "chat_id": sel_msg.chat.id,
        "msg_id": sel_msg.id,
        "user_id": listener.user_id,
        "caption": caption,
        "page": page,
        "page_size": page_size,
    }
    LOGGER.info(
        f"Direct Select session started for user {listener.user_id} with {len(contents)} items"
    )
    return True


async def _on_direct_select(_, query):
    data = query.data.split()
    action = data[1]
    sel_msg = query.message
    sess = DIRECT_SELECT_SESS.get(sel_msg.id)
    if not sess:
        await query.answer("Session expired.", show_alert=True)
        await delete_message(sel_msg)
        return
    if query.from_user.id != sess["user_id"]:
        await query.answer("This task is not for you!", show_alert=True)
        return

    listener = sess["listener"]
    details = sess["details"]
    contents = details.get("contents", [])
    total = len(contents)
    page = sess.get("page", 0)
    page_size = sess.get("page_size", MAX_PER_PAGE)

    if action == "tgl":
        await query.answer()
        try:
            idx = int(data[3])
        except Exception:
            return
        if 1 <= idx <= total:
            if idx in sess["selected"]:
                sess["selected"].remove(idx)
            else:
                sess["selected"].add(idx)
            sess["caption"] = _format_caption(
                details, sess["selected"], page, page_size
            )
            markup = _build_buttons(
                sess["selected"], total, sel_msg.id, page, page_size
            )
            await edit_message(sel_msg, text=sess["caption"], buttons=markup)
        return

    if action == "all":
        await query.answer("All selected")
        start = page * page_size + 1
        end = min(start + page_size - 1, total)
        sess["selected"].update(range(start, end + 1))
        sess["caption"] = _format_caption(details, sess["selected"], page, page_size)
        markup = _build_buttons(sess["selected"], total, sel_msg.id, page, page_size)
        await edit_message(sel_msg, text=sess["caption"], buttons=markup)
        return

    if action == "none":
        await query.answer("All cleared")
        start = page * page_size + 1
        end = min(start + page_size - 1, total)
        for gi in range(start, end + 1):
            sess["selected"].discard(gi)
        sess["caption"] = _format_caption(details, sess["selected"], page, page_size)
        markup = _build_buttons(sess["selected"], total, sel_msg.id, page, page_size)
        await edit_message(sel_msg, text=sess["caption"], buttons=markup)
        return

    if action == "page":
        direction = data[2]
        pages = (total + page_size - 1) // page_size if total else 1
        if direction == "curr":
            await query.answer()
            return
        if direction == "next":
            if page + 1 >= pages:
                await query.answer("Already at last page", show_alert=True)
                return
            page += 1
        elif direction == "prev":
            if page <= 0:
                await query.answer("Already at first page", show_alert=True)
                return
            page -= 1
        else:
            await query.answer()
            return
        sess["page"] = page
        sess["caption"] = _format_caption(details, sess["selected"], page, page_size)
        markup = _build_buttons(sess["selected"], total, sel_msg.id, page, page_size)
        await edit_message(sel_msg, text=sess["caption"], buttons=markup)
        await query.answer()
        return

    if action == "cancel":
        await query.answer("Cancelled")
        DIRECT_SELECT_SESS.pop(sel_msg.id, None)
        await delete_message(sel_msg)
        return

    if action == "start":
        if not sess["selected"]:
            await query.answer("No files selected!", show_alert=True)
            return
        await query.answer("Starting download...")
        sel_indices = sorted(list(sess["selected"]))
        new_contents = []
        new_total = 0
        for gi in sel_indices:
            item = contents[gi - 1]
            new_contents.append(item)
            size = item.get("size")
            new_total += safe_int_size(size)
        new_details = {
            k: v for k, v in details.items() if k not in ("contents", "total_size")
        }
        new_details["contents"] = new_contents
        new_details["total_size"] = (
            new_total if new_total > 0 else details.get("total_size", 0)
        )

        listener.link = new_details
        try:
            await delete_message(sel_msg)
        except Exception:
            pass
        DIRECT_SELECT_SESS.pop(sel_msg.id, None)
        await add_direct_download(listener, sess["path"])
        return


# Handler registration function for use in handlers.py
def register_direct_selector_handlers(bot):
    """Register direct selector callback handler"""
    bot.add_handler(
        CallbackQueryHandler(
            _on_direct_select,
            filters=regex("^dsel "),
        )
    )
