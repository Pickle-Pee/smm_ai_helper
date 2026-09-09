"""Telegram-safe complete text delivery (limits use UTF-16 code units)."""


def split_text(text: str, limit: int = 3500) -> list[str]:
    chunks, buffer, units = [], [], 0
    for char in text:
        cost = 2 if ord(char) > 0xFFFF else 1
        if units + cost > limit:
            chunks.append("".join(buffer))
            buffer, units = [], 0
        buffer.append(char)
        units += cost
    if buffer:
        chunks.append("".join(buffer))
    return chunks or ["Готово."]


async def send_text(message, text: str, *, reply_markup=None):
    chunks = split_text(text)
    for i, chunk in enumerate(chunks):
        await message.answer(chunk, parse_mode=None, reply_markup=reply_markup if i == len(chunks) - 1 else None)
