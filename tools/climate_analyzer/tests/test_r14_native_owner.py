import unittest
from unittest.mock import patch
from epw_climate_analyzer import byte_cache as b

class NativeOwnerReleaseTest(unittest.TestCase):
    def test_release_closes_only_its_owner_and_preserves_byte_limits(self):
        first=b._create_native_owner()
        second=b._create_native_owner()
        a=first.pool("private",1024,1,None)
        other=second.pool("private",1024,1,None)
        a.put("a",b"one")
        other.put("b",b"two")
        b._release_native_owner(first)
        self.assertTrue(first.closed)
        self.assertEqual(a.info()["entries"],0)
        self.assertFalse(second.closed)
        self.assertEqual(other.get("b"),b"two")
        self.assertEqual(first.pool("private",1024,1,None).info()["entries"],0)
        self.assertEqual(other.budget,1024)

    def test_native_owner_flag_defaults_off(self):
        with patch.dict("os.environ",{},clear=True):
            self.assertFalse(b.native_owner_enabled())
