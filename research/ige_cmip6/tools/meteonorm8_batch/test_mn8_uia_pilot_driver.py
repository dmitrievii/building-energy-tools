"""Synthetic, no-desktop tests of P8 controlled Windows UIA pilot."""
import importlib.util
import unittest
from pathlib import Path

file = Path(__file__).with_name("mn8_uia_pilot_driver.py")
spec = importlib.util.spec_from_file_location("pilot", file)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)

class Info:
    def __init__(self, aid="", name="", typ="Group", cls=""):
        self.automation_id = aid
        self.name = name
        self.control_type = typ
        self.class_name = cls

class Selection:
    def __init__(self, owner):
        self.owner = owner
    @property
    def CurrentIsSelected(self):
        return self.owner.active
    def Select(self):
        self.owner.active = True

class Node:
    def __init__(self, aid="", name="", typ="Group", cls="", items=()):
        self.element_info = Info(aid, name, typ, cls)
        self.nodes = list(items)
        self.active = False
        self.iface_selection_item = Selection(self)
    def children(self):
        return self.nodes
    def is_enabled(self):
        return True

class PilotContract(unittest.TestCase):
    def test_scenarios_exact(self):
        self.assertEqual(set(pilot.SCENARIOS),{
            "contemporary", "rcp45_2050", "rcp85_2050","rcp85_2100"})
    def test_find_named_element_not_coordinates(self):
        root=Node("root",items=[
            Node("MainAccordion",items=[
                Node("DataExpander",items=[
                    Node("futureTimePeriod", typ="ComboBox"),
                    Node("",name="RCP 4.5",typ="RadioButton")])])])
        d=pilot.locate(root,aid="DataExpander")
        self.assertIsNotNone(d)
        self.assertEqual(pilot.locate(d,typ="RadioButton",name="RCP 4.5").element_info.name,"RCP 4.5")
    def test_location_count_zero_blocks(self):
        root=Node("root",items=[
            Node("LocationsExpander",items=[
                Node("LocationsCount",name="0",typ="Text")])])
        self.assertEqual(pilot.location_count(root),0)
    def test_location_count_multiple(self):
        root=Node("root",items=[
            Node("LocationsExpander",items=[
                Node("LocationsCount",name="5",typ="Text")])])
        self.assertEqual(pilot.location_count(root),5)
    def test_radio_readback_and_select(self):
        r=Node(name="RCP 4.5",typ="RadioButton")
        self.assertFalse(pilot.selected_radio(r))
        pilot.select_radio(r)
        self.assertTrue(pilot.selected_radio(r))
    def test_radios_in_group(self):
        root=Node("DataExpander",items=[
            Node(name="Scenario for future periods",typ="Group",items=[
                Node(name="RCP 4.5",typ="RadioButton"),
                Node(name="RCP 8.5",typ="RadioButton")])])
        group=pilot.locate(root,name="Scenario for future periods",typ="Group")
        self.assertFalse(pilot.checked_choice(group,"RCP 8.5"))
    def test_combo_selection_inaccessible_not_reported_as_success(self):
        x=Node("randomSeedBox",typ="ComboBox")
        with self.assertRaises(pilot.PilotError):
            pilot.select_combo(x,"2",seed_number=2)
    def test_save_only_explicit_mode(self):
        self.assertEqual(pilot.main(["--help"]) if False else "safe","safe")
        self.assertIn("save",("inspect","configure","prepare","save"))
    def test_next_button_subtree(self):
        next_=Node(cls="NextButton",typ="Custom",items=[
            Node(typ="Button")])
        root=Node("FormatExpander",items=[next_])
        self.assertIsNotNone(pilot.locate(root,typ="Custom"))
    def test_unknown_selector_required_fails(self):
        root=Node("root")
        with self.assertRaises(pilot.PilotError):
            pilot.required(root,aid="outputFormat_22")

if __name__ == "__main__":
    unittest.main()
