from __future__ import annotations
import unittest
from pathlib import Path
REPO_ROOT=Path(__file__).resolve().parents[2]
class ThermalComfortIntegrationTests(unittest.TestCase):
    def test_tools_page_links_public_route(self):
        text=(REPO_ROOT/'website'/'site'/'tools'/'index.html').read_text(encoding='utf-8')
        self.assertIn('Thermal Comfort Studio',text)
        self.assertIn('https://dmitrievii.github.io/building-energy-tools/tools/thermal-comfort-studio/',text)
    def test_canonical_source_not_duplicated_under_website_site(self):
        self.assertTrue((REPO_ROOT/'tools'/'thermal_comfort_studio'/'index.html').is_file())
        self.assertFalse((REPO_ROOT/'website'/'site'/'tools'/'thermal-comfort-studio').exists())
if __name__=='__main__': unittest.main()
