from decimal import Decimal

from rayher_hr_payroll.demo import expected_demo_allocation


def test_expected_demo_allocation_matches_acceptance_numbers():
    assert expected_demo_allocation() == {
        "RD-CAP": Decimal("720.00"),
        "RD-EXP": Decimal("480.00"),
        "capitalized_total": Decimal("720.00"),
        "expensed_total": Decimal("480.00"),
    }


def test_upsert_doc_preserves_requested_name_for_series_doctypes(monkeypatch):
    from rayher_hr_payroll import demo

    class FakeDB:
        def exists(self, doctype, name):
            return False

    class FakeDoc:
        insert_kwargs = None

        def insert(self, **kwargs):
            self.insert_kwargs = kwargs

    fake_doc = FakeDoc()

    class FakeFrappe:
        db = FakeDB()

        def get_doc(self, payload):
            self.payload = payload
            return fake_doc

    fake_frappe = FakeFrappe()
    monkeypatch.setattr(demo, "_get_frappe", lambda: fake_frappe)

    doc = demo.upsert_doc("Project", "RD-CAP", {"project_name": "RD-CAP"})

    assert doc is fake_doc
    assert fake_frappe.payload["name"] == "RD-CAP"
    assert fake_doc.insert_kwargs["set_name"] == "RD-CAP"
