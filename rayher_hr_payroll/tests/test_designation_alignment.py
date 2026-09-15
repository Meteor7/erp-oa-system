import unittest
from rayher_hr_payroll.maintenance.designation_alignment import plan

class DesignationPlanTests(unittest.TestCase):
    def rows(self):
        return [dict(name=f"E{i}", employee_name=f"Person{i}", designation="Engineer") for i in range(85)]

    def test_only_reviewed_designation_changes(self):
        source = self.rows()
        current = [dict(x, designation=None) for x in source]
        result = plan(source, current)
        self.assertEqual(len(result["changes"]), 85)
        self.assertIsNone(result["remove"])

    def test_same_id_different_person_rejected(self):
        source = self.rows()
        current = [dict(x) for x in source]
        current[0]["employee_name"] = "Another person"
        with self.assertRaises(ValueError):
            plan(source, current)

    def test_excluded_person_must_be_unbound(self):
        source = self.rows()
        extra = dict(name="HR-EMP-90006", employee_name="演示员工182", user_id="someone")
        with self.assertRaises(ValueError):
            plan(source, source + [extra])
        extra["user_id"] = None
        self.assertEqual(plan(source, source + [extra])["remove"], "HR-EMP-90006")

    def test_unexpected_extra_is_rejected(self):
        source = self.rows()
        with self.assertRaises(ValueError):
            plan(source, source + [dict(name="unreviewed", employee_name="New hire")])
