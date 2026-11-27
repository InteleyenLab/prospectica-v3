import json
import os
import threading
from flask import request, has_request_context

_thread_local = threading.local()

_locales_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'locales')

# Load language registry
with open(os.path.join(_locales_dir, 'languages.json'), 'r', encoding='utf-8') as f:
    _languages = json.load(f)

# Load translation files
_translations = {}
for filename in os.listdir(_locales_dir):
    if filename.endswith('.json') and filename != 'languages.json':
        locale_name = filename[:-5]
        with open(os.path.join(_locales_dir, filename), 'r', encoding='utf-8') as f:
            _translations[locale_name] = json.load(f)


def set_locale(locale: str = 'es'):
    """Set locale for current thread. Call at the start of background threads."""
    _thread_local.locale = 'es'


def get_locale() -> str:
    return 'es'


def t(key: str, **kwargs) -> str:
    messages = _translations.get('es', {})

    value = messages
    for part in key.split('.'):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = None
            break

    if value is None:
        return key

    if kwargs:
        for k, v in kwargs.items():
            value = value.replace(f'{{{k}}}', str(v))

    return value


def get_language_instruction() -> str:
    return (
        "INSTRUCCIÓN OBLIGATORIA DE IDIOMA: Debes redactar TODO el contenido, títulos de secciones, "
        "resúmenes, análisis y conclusiones ESTRICTAMENTE EN ESPAÑOL. "
        "Prohibido escribir títulos, encabezados o párrafos en chino o en inglés."
    )
