# Small helpers for client-server messages.


def message(message_type, **fields):
    return {"type": message_type, **fields}


def error(message_text):
    return message("error", message=message_text)
