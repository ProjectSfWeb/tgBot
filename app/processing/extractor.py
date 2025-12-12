from typing import Dict, Any, List, Set


def _is_deleted_account(name: str | None, username: str | None) -> bool:
    """
    Эвристика для удалённых аккаунтов.
    """
    if not name and not username:
        return True
    if name and "deleted account" in name.lower():
        return True
    return False


def extract_entities(parsed: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Извлекает:
    - participants: авторы сообщений (уникальные по имени, т.к. username в экспорте отсутствует)
    - mentions: упомянутые @username
    - channels: каналы (определяются по is_channel)
    """

    messages = parsed.get("messages", [])

    participants_map: Dict[str, Dict[str, Any]] = {}
    channels_map: Dict[str, Dict[str, Any]] = {}
    mentions_set: Set[str] = set()

    for m in messages:
        frm = m.get("from") or {}
        name = frm.get("name") or None
        username = frm.get("username")  # всегда None, оставим для совместимости
        is_channel = frm.get("is_channel", False)

        # ---- КАНАЛЫ ----
        if is_channel:
            key = username or name or "unknown_channel"
            if key not in channels_map:
                channels_map[key] = {
                    "name": name,
                    "username": username
                }

        # ---- УЧАСТНИКИ ----
        # В Telegram Desktop username отсутствует, поэтому различаем по имени
        if name:
            if name not in participants_map:
                participants_map[name] = {
                    "name": name,
                    "username": username,   # всегда None, но пусть поле будет
                    "has_channel": is_channel,
                }
            else:
                # обновляем флаг: если хоть раз писал как канал
                participants_map[name]["has_channel"] = (
                    participants_map[name]["has_channel"] or is_channel
                )

        # ---- УПОМИНАНИЯ ----
        for u in m.get("mentions", []):
            if u:
                mentions_set.add(u)

    return {
        "participants": list(participants_map.values()),
        "mentions": [{"username": u} for u in sorted(list(mentions_set))],
        "channels": list(channels_map.values()),
    }
