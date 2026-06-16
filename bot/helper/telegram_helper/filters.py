from pyrogram.filters import create
from pyrogram.enums import ChatType

from ... import sudo_users, user_data
from ...core.config_manager import Config
from .tg_utils import chat_info


class CustomFilters:
    """
    Custom filters for the bot to manage user permissions.
    """

    @staticmethod
    async def owner_filter(_, update):
        """
        Filter to check if the user is the owner of the bot.
        """
        user = update.from_user or update.sender_chat
        return user.id == Config.OWNER_ID

    owner = create(owner_filter)

    @staticmethod
    async def authorized_user(_, update):
        """
        Filter to check if a user is authorized to use the bot's general commands.
        This allows access if FREE_FOR_EVERYONE is True, or if the user/chat
        is individually authorized.
        """
        user = update.from_user or update.sender_chat
        uid = user.id
        chat_id = update.chat.id

        # Free for everyone logic: grants general access to all users.
        if getattr(Config, "FREE_FOR_EVERYONE", False):
            return True

        # Owner check
        if uid == Config.OWNER_ID:
            return True

        # User Data Checks for authorized users or sudoers
        if uid in user_data:
            if user_data[uid].get("AUTH", False) or user_data[uid].get("SUDO", False):
                return True

        # Chat auth check (for authorized groups/channels)
        if chat_id in user_data and user_data[chat_id].get("AUTH", False):
            return True

        return False

    authorized = create(authorized_user)

    @staticmethod
    async def authorized_usetting(_, update):
        """
        Filter to check if a user is authorized to change their settings.
        """
        uid = (update.from_user or update.sender_chat).id

        # Free for everyone: all pass
        if getattr(Config, "FREE_FOR_EVERYONE", False):
            return True

        # Directly authorized (owner/sudo/etc)
        if await CustomFilters.authorized_user("", update):
            return True

        # Additionally, for PM, check if user is member/admin in an authorized channel/group
        if update.chat.type == ChatType.PRIVATE:
            for channel_id in user_data:
                if not (
                    user_data[channel_id].get("is_auth")
                    and str(channel_id).startswith("-100")
                ):
                    continue
                try:
                    chat = await chat_info(str(channel_id))
                    if chat:  # Check if chat object is not None
                        member = await chat.get_member(uid)
                        if member:
                            return True
                except Exception:
                    continue
        return False

    authorized_uset = create(authorized_usetting)

    @staticmethod
    async def sudo_user(_, update):
        """
        Filter to check if a user has sudo privileges.
        This check is independent of FREE_FOR_EVERYONE to protect sensitive commands.
        """
        user = update.from_user or update.sender_chat
        uid = user.id

        # The FREE_FOR_EVERYONE check is intentionally removed here.
        # Sudo commands should always be restricted to the owner and sudo users.
        return bool(
            uid == Config.OWNER_ID
            or (uid in user_data and user_data[uid].get("SUDO"))
            or uid in sudo_users
        )

    sudo = create(sudo_user)

    @staticmethod
    async def can_view_user_settings(_, update):
        """
        Filter that allows ANYONE to view their user settings, always.
        """
        return True

    can_view_usets = create(can_view_user_settings)

    @staticmethod
    async def pm_or_group(_, update):
        """
        Permissive filter that allows both private and group chats.
        Useful to broaden certain commands to work in PM as well as groups.
        """
        return True

    pm_or_group = create(pm_or_group)
