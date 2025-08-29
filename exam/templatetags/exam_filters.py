from django import template

register = template.Library()

@register.filter
def get_option(question, index):
    try:
        options = question.options.all()  # 이 부분은 질문에 따라 조정해야 합니다.
        return options[index - 1] if 0 <= index - 1 < len(options) else None
    except (AttributeError, IndexError):
        return None
