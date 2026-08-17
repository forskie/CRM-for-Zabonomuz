from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """Access a dict value by a variable key, e.g. {{ lessons_by_day|get_item:day }}."""
    if mapping is None:
        return None
    return mapping.get(key)
