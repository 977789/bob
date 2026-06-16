from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class ButtonMaker:
    def __init__(self):
        self.buttons = {
            "default": [],
            "header": [],
            "f_body": [],
            "l_body": [],
            "footer": [],
        }

    def url_button(self, key, link, position=None):
        target = position if position in self.buttons else "default"
        self._add_button(target, InlineKeyboardButton(text=key, url=link))

    def data_button(self, key, data, position=None):
        target = position if position in self.buttons else "default"
        self._add_button(target, InlineKeyboardButton(text=key, callback_data=data))

    def _add_button(self, section, button):
        if len(button.text) > 28:
            self.buttons[section].append([button])
        else:
            self.buttons[section].append(button)

    def build_menu(self, b_cols=1, h_cols=8, fb_cols=2, lb_cols=2, f_cols=8):
        def chunk(lst, n):
            return [lst[i : i + n] for i in range(0, len(lst), n)]

        def process_section(section, cols):
            lines = []
            row = []
            for item in self.buttons[section]:
                if isinstance(item, list):
                    lines.append(item)
                else:
                    row.append(item)
                    if len(row) >= cols:
                        lines.append(row)
                        row = []
            if row:
                lines.append(row)
            return lines

        menu = process_section("default", b_cols)
        if self.buttons["header"]:
            menu = process_section("header", h_cols) + menu
        for key, cols in (("f_body", fb_cols), ("l_body", lb_cols), ("footer", f_cols)):
            if self.buttons[key]:
                menu += process_section(key, cols)

        return InlineKeyboardMarkup(menu) if menu else None

    def reset(self):
        for key in self.buttons:
            self.buttons[key].clear()
