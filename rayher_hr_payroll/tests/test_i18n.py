from types import SimpleNamespace

import pytest

from rayher_hr_payroll.i18n import (
    SUPPORTED_LANGUAGES,
    get_language_options,
    normalize_language,
    set_language,
)


class FakeDB:
    def __init__(self):
        self.set_values = []

    def set_value(self, doctype, name, fieldname, value):
        self.set_values.append((doctype, name, fieldname, value))


class FakeCache:
    def __init__(self):
        self.deleted = []

    def hdel(self, name, key):
        self.deleted.append((name, key))


class FakeFrappe:
    def __init__(self, user='user@example.com'):
        self.session = SimpleNamespace(user=user)
        self.local = SimpleNamespace(lang='en')
        self.db = FakeDB()
        self.cache = FakeCache()
        self.cleared_users = []
        self.thrown = []

    def clear_cache(self, user=None):
        self.cleared_users.append(user)

    def throw(self, message):
        self.thrown.append(str(message))
        raise ValueError(str(message))

    def _(self, message):
        return f'T:{message}'


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [('zh', 'zh'), ('zh-CN', 'zh'), ('fr-FR', 'fr'), ('fr_FR', 'fr'), (' EN ', 'en')],
)
def test_normalize_language_accepts_supported_language_and_regions(raw, expected):
    assert normalize_language(raw) == expected


@pytest.mark.parametrize('raw', ['de', 'es-MX', '', None])
def test_normalize_language_rejects_unsupported_language(raw):
    with pytest.raises(ValueError, match='Unsupported language|Language is required'):
        normalize_language(raw)


def test_language_options_are_limited_to_chinese_english_and_french():
    assert set(SUPPORTED_LANGUAGES) == {'zh', 'en', 'fr'}
    assert [row['value'] for row in get_language_options()] == ['zh', 'en', 'fr']


def test_set_language_persists_current_user_language_and_clears_cache():
    fake = FakeFrappe()

    result = set_language('fr-FR', frappe_module=fake)

    assert result == {'language': 'fr', 'reload': True}
    assert fake.local.lang == 'fr'
    assert fake.db.set_values == [('User', 'user@example.com', 'language', 'fr')]
    assert fake.cleared_users == ['user@example.com']
    assert ('merged_translations', 'fr') in fake.cache.deleted
    assert ('lang_user_translations', 'fr') in fake.cache.deleted


def test_set_language_rejects_guest_user():
    fake = FakeFrappe(user='Guest')

    with pytest.raises(ValueError, match='Login is required'):
        set_language('zh', frappe_module=fake)
