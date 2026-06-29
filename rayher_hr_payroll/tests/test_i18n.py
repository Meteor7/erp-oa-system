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
    'RD Cost Allocation',
    'RD Expense Import',
    'RD Period Lock',
    'Recognized RD Type',
    'Standard Daily Hours',
    'Set a default company before loading Rayher demo data.',
    # Report names + labels (Babel-unextractable; registered via translatable_labels._lt).
    'RD Allocation Matrix',
    'RD Timesheet Exceptions',
    'Expense Item',
    'Missing Timesheet',
    'Unclassified R&D Hours',
    # Validation messages raised via injected translate() in controls/*.py.
    'A submitted RD Expense Import already exists for period {0} ({1}); importing the same period twice would double-count R&D cost.',
    'R&D period {0} is locked; timesheet changes require a correction workflow.',
    'Project {0} is not enabled for R&D timesheet entry.',
    'Project {0} needs capitalization start and end dates before R&D timesheet entry.',
    'Statutory holiday overtime cannot be converted into compensatory leave; it must be paid according to policy.',
    'Year and month must be valid numbers.',
}


def _locale_dir():
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / 'locale'


def _po_token(token):
    import ast

    token = token.strip()
    return ast.literal_eval(token) if token.startswith('"') else ''


def _parse_po(path):
    """Minimal gettext PO reader (msgid -> msgstr); stdlib only, no babel dependency."""
    entries = {}
    msgid_parts = []
    msgstr_parts = []
    state = None
    lines = path.read_text(encoding='utf-8').split('\n')
    for line in lines + ['']:
        if line.startswith('msgid '):
            if state is not None:
                entries[''.join(msgid_parts)] = ''.join(msgstr_parts)
            msgid_parts = [_po_token(line[len('msgid '):])]
            msgstr_parts = []
            state = 'id'
        elif line.startswith('msgstr '):
            msgstr_parts = [_po_token(line[len('msgstr '):])]
            state = 'str'
        elif line[:1] == '"':
            (msgid_parts if state == 'id' else msgstr_parts).append(_po_token(line))
    if state is not None:
        entries[''.join(msgid_parts)] = ''.join(msgstr_parts)
    entries.pop('', None)
    return entries


def _load_po(language):
    return _parse_po(_locale_dir() / f'{language}.po')


@pytest.mark.parametrize('language', ['zh', 'fr'])
def test_translation_files_exist_and_parse_as_po(language):
    assert _load_po(language)


def test_pot_template_covers_required_strings():
    ids = set(_parse_po(_locale_dir() / 'main.pot'))

    assert REQUIRED_TRANSLATION_STRINGS <= ids


def test_chinese_locale_covers_required_rayher_strings():
    translations = _load_po('zh')

    missing = REQUIRED_TRANSLATION_STRINGS - set(translations)
    assert missing == set()
    assert all(translations[source] for source in REQUIRED_TRANSLATION_STRINGS)


def test_manifest_includes_translation_po_files():
    from pathlib import Path

    manifest = (Path(__file__).resolve().parents[2] / 'MANIFEST.in').read_text()

    assert '*.po' in manifest
    assert '*.pot' in manifest


def test_set_language_is_whitelisted_for_post_http_calls():
    frappe = pytest.importorskip("frappe")
    from rayher_hr_payroll.i18n import set_language

    assert set_language in frappe.whitelisted
    assert frappe.allowed_http_methods_for_whitelisted_func[set_language] == ['POST']

def test_core_string_corrections_csv_overrides_mistranslations():
    """translations/zh.csv ships only core-string corrections; app strings live in PO."""
    import csv
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "translations" / "zh.csv"
    rows = {r[0]: r[1] for r in csv.reader(path.open(encoding="utf-8")) if len(r) >= 2}
    expected = {"Like": "包含", "Not Like": "不包含", "Clear": "清除", "Reset": "重置", "Done": "完成"}
    for source, translation in expected.items():
        assert rows.get(source) == translation
