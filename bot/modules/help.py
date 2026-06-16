from ..helper.ext_utils.bot_utils import COMMAND_USAGE, new_task
from ..helper.ext_utils.help_messages import (
    YT_HELP_DICT,
    MIRROR_HELP_DICT,
    CLONE_HELP_DICT,
    VT_HELP_DICT,
)
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    edit_message,
    delete_message,
    send_message,
)
from ..helper.ext_utils.help_messages import help_string


@new_task
async def arg_usage(_, query):
    data = query.data.split()
    message = query.message
    await query.answer()
    if data[1] == "close":
        await delete_message(message)
        return await delete_message(message.reply_to_message)
    pg_no = int(data[3])
    if data[1] == "nex":
        if data[2] == "mirror":
            await edit_message(
                message, COMMAND_USAGE["mirror"][0], COMMAND_USAGE["mirror"][pg_no + 1]
            )
        elif data[2] == "yt":
            await edit_message(
                message, COMMAND_USAGE["yt"][0], COMMAND_USAGE["yt"][pg_no + 1]
            )
        elif data[2] == "clone":
            await edit_message(
                message, COMMAND_USAGE["clone"][0], COMMAND_USAGE["clone"][pg_no + 1]
            )
        elif data[2] == "vt":
            await edit_message(
                message,
                COMMAND_USAGE.get("vt", ["Video Tools", ""])[0],
                COMMAND_USAGE.get("vt", ["", ""])[pg_no + 1],
            )
    elif data[1] == "pre":
        if data[2] == "mirror":
            await edit_message(
                message, COMMAND_USAGE["mirror"][0], COMMAND_USAGE["mirror"][pg_no + 1]
            )
        elif data[2] == "yt":
            await edit_message(
                message, COMMAND_USAGE["yt"][0], COMMAND_USAGE["yt"][pg_no + 1]
            )
        elif data[2] == "clone":
            await edit_message(
                message, COMMAND_USAGE["clone"][0], COMMAND_USAGE["clone"][pg_no + 1]
            )
        elif data[2] == "vt":
            await edit_message(
                message,
                COMMAND_USAGE.get("vt", ["Video Tools", ""])[0],
                COMMAND_USAGE.get("vt", ["", ""])[pg_no + 1],
            )
    elif data[1] == "back":
        if data[2] == "m":
            await edit_message(
                message, COMMAND_USAGE["mirror"][0], COMMAND_USAGE["mirror"][pg_no + 1]
            )
        elif data[2] == "y":
            await edit_message(
                message, COMMAND_USAGE["yt"][0], COMMAND_USAGE["yt"][pg_no + 1]
            )
        elif data[2] == "c":
            await edit_message(
                message, COMMAND_USAGE["clone"][0], COMMAND_USAGE["clone"][pg_no + 1]
            )
        elif data[2] == "v":
            await edit_message(
                message,
                COMMAND_USAGE.get("vt", ["Video Tools", ""])[0],
                COMMAND_USAGE.get("vt", ["", ""])[pg_no + 1],
            )
    elif data[1] == "mirror":
        buttons = ButtonMaker()
        buttons.data_button("Back", f"help back m {pg_no}")
        button = buttons.build_menu()
        await edit_message(message, MIRROR_HELP_DICT[data[2]], button)
    elif data[1] == "yt":
        buttons = ButtonMaker()
        buttons.data_button("Back", f"help back y {pg_no}")
        button = buttons.build_menu()
        await edit_message(message, YT_HELP_DICT[data[2]], button)
    elif data[1] == "clone":
        buttons = ButtonMaker()
        buttons.data_button("Back", f"help back c {pg_no}")
        button = buttons.build_menu()
        await edit_message(message, CLONE_HELP_DICT[data[2]], button)
    elif data[1] == "vt":
        buttons = ButtonMaker()
        buttons.data_button("Back", f"help back v {pg_no}")
        button = buttons.build_menu()
        await edit_message(message, VT_HELP_DICT[data[2]], button)


@new_task
async def bot_help(_, message):
    buttons = ButtonMaker()
    # Main sections
    buttons.data_button("Mirror/Leech", f"help back m 0")
    buttons.data_button("YouTube", f"help back y 0")
    buttons.data_button("Clone", f"help back c 0")
    buttons.data_button("Video Tools", f"help vt main 0")
    # Quick direct topics for convenience
    for name in list(MIRROR_HELP_DICT.keys())[1:6]:
        buttons.data_button(name, f"help mirror {name} 0")
    for name in list(YT_HELP_DICT.keys())[1:4]:
        buttons.data_button(name, f"help yt {name} 0")
    for name in list(CLONE_HELP_DICT.keys())[1:3]:
        buttons.data_button(name, f"help clone {name} 0")
    for name in ["Watermark", "Intro-Sub", "Merge", "Convert", "Reorder"]:
        buttons.data_button(name, f"help vt {name} 0")
    buttons.data_button("Close", "help close", position="footer")
    await send_message(message, help_string, buttons.build_menu(2))
