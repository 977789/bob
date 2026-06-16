from .. import cached_dict
from ..helper.ext_utils.bot_utils import new_task
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    is_admin,
)


@new_task
async def verify_anno(_, query):
    message = query.message
    data = query.data.split()
    msg_id = int(data[2])
    if msg_id not in cached_dict:
        return await edit_message(message, "<b>Old Verification Message</b>")
    user = query.from_user
    isadmin = await is_admin(message, user.id)
    if data[1] == "admin" and isadmin:
        await query.answer(
            f"Username: {user.username}\nYour userid : {user.id}", show_alert=True
        )
        cached_dict[msg_id] = user
        await delete_message(message)
    elif data[1] == "admin":
        await query.answer("You are not an admin", show_alert=True)
    else:
        await query.answer()
        await edit_message(message, "<b>Cancelled Verification</b>")
