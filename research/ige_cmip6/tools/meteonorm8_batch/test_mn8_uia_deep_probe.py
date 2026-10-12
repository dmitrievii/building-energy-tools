"""Synthetic deterministic checks for read-only scoped Meteonorm UIA diagnostic."""
import importlib.util
import json
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("mn8_uia_deep_probe.py")
spec = importlib.util.spec_from_file_location("probe", SOURCE)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

class Info:
    def __init__(self, auto, typ, name):
        self.automation_id = auto
        self.control_type = typ
        self.class_name = "Wpf" + typ
        self.name = name

class Node:
    def __init__(self, auto, typ="Group", name="", children=()):
        self.element_info = Info(auto, typ, name)
        self._children = list(children)
    def children(self):
        return self._children
    def is_enabled(self):
        return True

class Contracts(unittest.TestCase):
    def test_expected_windows_scopes(self):
        self.assertEqual(p.TARGET_IDS, ("DataExpander","FormatExpander","OutputExpander"))
    def test_target_found_nested_in_wpf_accordion(self):
        tree=Node("window",children=[Node("MainAccordion",children=[
            Node("DataExpander",children=[Node("",children=[
                Node("",name="Scenario for future periods",children=[
                    Node("ScenarioSelect",typ="ComboBox",name="SSP/RCP")
                ])])])])])
        targets=p.find_target_nodes(tree)
        self.assertIn("DataExpander", targets)
        report,meta=p.inspect_subtree(targets["DataExpander"],relative_max_depth=7)
        self.assertEqual(report["children"][0]["children"][0]["children"][0]["automation_id"],"ScenarioSelect")
        self.assertFalse(meta["truncated"])
    def test_edit_contents_and_secrets_excluded(self):
        root=Node("DataExpander",children=[
            Node("a","Edit","USER_LICENSE_KEY"),
            Node("b","Password","password 123"),
            Node("c","Text","Activation code XY"),
            Node("d","ComboBox","Period")])
        tree,_=p.inspect_subtree(root)
        js=json.dumps(tree)
        self.assertNotIn("USER_LICENSE_KEY",js)
        self.assertNotIn("password 123",js)
        self.assertNotIn("Activation code XY",js)
        self.assertIn("Period",js)
    def test_budget_truncates_without_crashing(self):
        tree,_=p.inspect_subtree(Node("DataExpander",children=[
            Node(str(i)) for i in range(20)]),max_nodes=5)
        self.assertIsNotNone(tree)
    def test_label_limiter(self):
        self.assertEqual(len(p.allowed_name("Text","x"*250)),150)

if __name__ == "__main__":
    unittest.main()
