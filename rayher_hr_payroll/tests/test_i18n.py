from types import SimpleNamespace

import pytest

from rayher_hr_payroll.i18n import (
    SUPPORTED_LANGUAGES,
    _set_language,
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

    result = _set_language('fr-FR', frappe_module=fake)

    assert result == {'language': 'fr', 'reload': True}
    assert fake.local.lang == 'fr'
    assert fake.db.set_values == [('User', 'user@example.com', 'language', 'fr')]
    assert fake.cleared_users == ['user@example.com']
    assert ('merged_translations', 'fr') in fake.cache.deleted
    assert ('lang_user_translations', 'fr') in fake.cache.deleted


def test_set_language_rejects_guest_user():
    fake = FakeFrappe(user='Guest')

    with pytest.raises(ValueError, match='Login is required'):
        _set_language('zh', frappe_module=fake)


def test_public_set_language_signature_exposes_only_language():
    import inspect

    assert list(inspect.signature(set_language).parameters) == ['language']


REQUIRED_TRANSLATION_STRINGS = {
    'Rayher HR Payroll',
    'Review R&D timesheet',
    'Voucher No',
    'Expense Item',
    'Employee',
    'Employee Name',
    'Exception Type',
    'Message',
    'Missing Timesheet',
    'Unclassified R&D Hours',
    '{0}-{1:02d} has no submitted timesheet hours.',
    'Logged {0} h on R&D projects but rd_personnel_type is ' + chr(39) + '{1}' + chr(39) + '; excluded from R&D allocation.',
    'R&D period {0} is locked; timesheet changes require a correction workflow.',
    'Project {0} is not enabled for R&D timesheet entry.',
    'Project {0} needs capitalization start and end dates before R&D timesheet entry.',
    'Statutory holiday overtime cannot be converted into compensatory leave; it must be paid according to policy.',
    'A submitted RD Expense Import already exists for period {0} ({1}); importing the same period twice would double-count R&D cost.',
    'Set a default company before loading Rayher demo data.',
}


def _translation_path(language):
    from pathlib import Path

    app_root = Path(__file__).resolve().parents[1]
    return app_root / 'translations' / f'{language}.csv'


def _load_translation_csv(language):
    import csv

    with _translation_path(language).open(encoding='utf-8', newline='') as handle:
        return {row[0]: row[1] for row in csv.reader(handle) if len(row) >= 2}


@pytest.mark.parametrize('language', ['zh', 'fr'])
def test_translation_files_exist_and_parse_as_utf8_csv(language):
    translations = _load_translation_csv(language)

    assert translations


@pytest.mark.parametrize('language', ['zh', 'fr'])
def test_translation_files_cover_required_rayher_strings(language):
    translations = _load_translation_csv(language)

    missing = REQUIRED_TRANSLATION_STRINGS - set(translations)
    assert missing == set()
    assert all(translations[source] for source in REQUIRED_TRANSLATION_STRINGS)


def test_manifest_includes_translation_csv_files():
    from pathlib import Path

    manifest = (Path(__file__).resolve().parents[2] / 'MANIFEST.in').read_text()

    assert '*.csv' in manifest


def test_set_language_is_whitelisted_for_post_http_calls():
    import frappe
    from rayher_hr_payroll.i18n import set_language

    assert set_language in frappe.whitelisted
    assert frappe.allowed_http_methods_for_whitelisted_func[set_language] == ['POST']
