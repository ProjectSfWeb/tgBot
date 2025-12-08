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
    - participants: авторы сообщений (уникальные по username/имени)
    - mentions: упомянутые @username
    - channels: сообщения, помеченные каналами

    Нормализует и убирает дубликаты/удалённые.
    """
    messages = parsed.get("messages", [])
    participants_map: Dict[str, Dict[str, Any]] = {}
    participants_no_username: List[Dict[str, Any]] = []
    mentions_set: Set[str] = set()
    channels_map: Dict[str, Dict[str, Any]] = {}

    for m in messages:
        frm = m.get("from") or {}
        name = (frm.get("name") or "") or None
        username = frm.get("username") or None
        is_channel = bool(frm.get("is_channel"))

        # Каналы
        if is_channel:
            key = username or name or "channel_unknown"
            if key not in channels_map:
                channels_map[key] = {"name": name, "username": username}

        # Участники
        if not _is_deleted_account(name, username):
            if username:
                if username not in participants_map:
                    participants_map[username] = {
                        "name": name,
                        "username": username,
                        "bio": None,  # Можем заполнить, если доступно из JSON (в некоторых экспортных форматах)
                        "registered_at": None,
                        "has_channel": is_channel,
                    }
                else:
                    # Обновим флаги при необходимости
                    participants_map[username]["has_channel"] = participants_map[username]["has_channel"] or is_channel
            else:
                # Без username — учтём по имени (может дублироваться, поэтому не включаем в конечный список username)
                # Можно опционально вести учёт name-only
                participants_no_username.append(
                    {
                        "name": name,
                        "username": None,
                        "bio": None,
                        "registered_at": None,
                        "has_channel": is_channel,
                    }
                )

        # Упоминания
        for u in m.get("mentions", []):
            if u:
                mentions_set.add(u)

    participants = list(participants_map.values())
    mentions = [{"username": u} for u in sorted(list(mentions_set))]
    channels = list(channels_map.values())

    return {
        "participants": participants,
        "mentions": mentions,
        "channels": channels,
    }