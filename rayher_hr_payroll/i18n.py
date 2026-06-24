from __future__ import annotations

from typing import Any

try:  # frappe is unavailable during pure unit-test collection
    import frappe
except Exception:  # pragma: no cover
    frappe = None

SUPPORTED_LANGUAGES = {
    'zh': {'label': '\u4e2d\u6587', 'name': 'Chinese'},
    'en': {'label': 'English', 'name': 'English'},
    'fr': {'label': 'Fran\u00e7ais', 'name': 'French'},
}

_TRANSLATION_CACHE_KEYS = ('merged_translations', 'lang_user_translations')


def _whitelist(**kwargs):
    if frappe is not None:
        return frappe.whitelist(**kwargs)
    def _noop(fn):
        return fn
    return _noop


def _get_frappe():
    return frappe


def normalize_language(language: str | None) -> str:
    if language is None or not str(language).strip():
        raise ValueError('Language is required')
    code = str(language).strip().replace('_', '-').lower()
    primary = code.split('-', 1)[0]
    if primary in SUPPORTED_LANGUAGES:
        return primary
    raise ValueError(f'Unsupported language: {language}')


def get_language_options() -> list[dict[str, str]]:
    return [
        {'value': code, 'label': meta['label'], 'name': meta['name']}
        for code, meta in SUPPORTED_LANGUAGES.items()
    ]


def _translated(frappe_module: Any, message: str) -> str:
    translate = getattr(frappe_module, '_', None)
    return str(translate(message) if callable(translate) else message)


def _throw(frappe_module: Any, message: str) -> None:
    translated = _translated(frappe_module, message)
    throw = getattr(frappe_module, 'throw', None)
    if callable(throw):
        throw(translated)
    raise ValueError(translated)


def _clear_translation_cache(frappe_module: Any, language: str) -> None:
    cache = getattr(frappe_module, 'cache', None)
    hdel = getattr(cache, 'hdel', None)
    if callable(hdel):
        for key in _TRANSLATION_CACHE_KEYS:
            hdel(key, language)


def _set_current_user_language(language: str, frappe_module: Any) -> dict[str, Any]:
    user = getattr(getattr(frappe_module, 'session', None), 'user', None)
    if not user or user == 'Guest':
        _throw(frappe_module, 'Login is required to change language.')

    frappe_module.db.set_value('User', user, 'language', language)
    if hasattr(frappe_module, 'local'):
        frappe_module.local.lang = language
    clear_cache = getattr(frappe_module, 'clear_cache', None)
    if callable(clear_cache):
        clear_cache(user=user)
    _clear_translation_cache(frappe_module, language)
    return {'language': language, 'reload': True}


def _set_language(language: str, frappe_module: Any | None = None) -> dict[str, Any]:
    frappe = frappe_module or _get_frappe()
    try:
        normalized = normalize_language(language)
    except ValueError as exc:
        _throw(frappe, str(exc))
    return _set_current_user_language(normalized, frappe)


@_whitelist(methods=['POST'])
def set_language(language: str) -> dict[str, Any]:
    return _set_language(language)
