"""Small, simple helpers — expected low risk."""


def slugify(text):
    """Lower-case, dash-separated identifier."""
    return "-".join(text.lower().split())


def clamp(value, low, high):
    return max(low, min(value, high))


def chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]
