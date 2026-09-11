from __future__ import annotations
import unittest
from pathlib import Path
REPO_ROOT=Path(__file__).resolve().parents[2]
WORKFLOW=REPO_ROOT/'.github'/'workflows'/'pages-deploy.yml'
DEPLOYMENT_DOC=REPO_ROOT/'website'/'deployment'/'GITHUB_PAGES.md'
class PagesDeploymentContractTests(unittest.TestCase):
    def test_pages_workflow_exists_and_assembles_site_with_thermal_comfort_tool(self):
        self.assertTrue(WORKFLOW.is_file()); text=WORKFLOW.read_text(encoding='utf-8')
        for token in ['actions/configure-pages@v5','actions/upload-pages-artifact@v3','actions/deploy-pages@v4','path: _site','pages: write','id-token: write','python website/scripts/check_static_site.py','python -m unittest discover -s website/tests','tools/thermal_comfort_studio/scripts/build_static_dist.py','_site/tools/thermal-comfort-studio']:
            self.assertIn(token,text)
    def test_pages_deploy_is_main_only(self):
        text=WORKFLOW.read_text(encoding='utf-8'); self.assertIn('branches:\n      - main',text); self.assertNotIn('pull_request:',text)
    def test_default_project_url_and_release_boundary_are_documented(self):
        self.assertTrue(DEPLOYMENT_DOC.is_file()); text=DEPLOYMENT_DOC.read_text(encoding='utf-8')
        self.assertIn('https://dmitrievii.github.io/building-energy-tools/',text); self.assertIn('website/site/',text); self.assertIn('publication/legal/privacy gate',text); self.assertIn('live-host audit',text)
if __name__=='__main__': unittest.main()
