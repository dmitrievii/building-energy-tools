"""Offline fixture contracts for the IGE 81-artifact reproducibility freeze verifier."""
from __future__ import annotations
import io,json,hashlib,tempfile,unittest
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from verify_ige_research_freeze import verify_zip,KNOWN_SHA256,KNOWN_LENGTH

class ScientificFreezeIntegrityTests(unittest.TestCase):
    def fixture(self,where,*,tamper_internal=False,tamper_outer=False):
        src=io.BytesIO()
        with ZipFile(src,"w",ZIP_DEFLATED) as z:z.writestr("native_source.json",b'{"verified": true}')
        zipbytes=src.getvalue()
        raw=b'{"verified": true}'
        inner={"path":"native_source.json","sha256":hashlib.sha256(raw).hexdigest(),
               "bytes":len(raw)}
        r={"path":"model_window_sources/model.zip","role":"model_window",
           "model":"ACCESS-CM2","window":"historical-1995-2014",
           "bytes":len(zipbytes),"sha256":hashlib.sha256(zipbytes).hexdigest(),
           "zip_member_sha256":[inner]}
        if tamper_internal:inner["sha256"]="f"*64
        m={"archive_count":1,"archives":[r]}
        out=Path(where)/"portable.zip"
        with ZipFile(out,"w",ZIP_DEFLATED) as z:
            z.writestr("FREEZE/MANIFEST.json",json.dumps(m))
            z.writestr("FREEZE/model_window_sources/model.zip",
                        zipbytes+b"tampered" if tamper_outer else zipbytes)
        return out

    def test_fixture_sha_and_nested_source_verified(self):
        with tempfile.TemporaryDirectory() as d:
            verdict=verify_zip(self.fixture(d),enforce_canonical=False)
            self.assertEqual(verdict["status"],"PASS")
            self.assertEqual(verdict["GCM_model_period_combinations"],1)

    def test_mutated_nested_source_sha_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            verdict=verify_zip(self.fixture(d,tamper_internal=True),enforce_canonical=False)
            self.assertEqual(verdict["status"],"FAIL")
            self.assertTrue(any("Embedded SHA256" in x for x in verdict["errors"]))

    def test_changed_original_zip_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            verdict=verify_zip(self.fixture(d,tamper_outer=True),enforce_canonical=False)
            self.assertEqual(verdict["status"],"FAIL")
            self.assertTrue(any("ZIP checksum" in x for x in verdict["errors"]))

    def test_canonical_manifest_includes_institutional_custody_digests(self):
        self.assertEqual(KNOWN_SHA256,
                         "2c3ceecaf83aa3ff2b3e19d109d866111f1145eb5fe48ac6a4fdd010b27a22d7")
        self.assertEqual(KNOWN_LENGTH,68062328)

if __name__=="__main__":unittest.main()
