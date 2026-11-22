import unittest,json
from epw_climate_analyzer.r143_scientific_parity import _row

class TestScientificFingerprints(unittest.TestCase):
    def test_arrays_distinguish_weather_not_trace_names(self):
        def row(y,name="Temperature",unit="C"):
            return _row(json.dumps({"data":[{"x":[1,2],"y":y,"name":name}],"layout":{"yaxis":{"title":unit}}}),{"source":"test"},"interpretation")
        a=row([10,20])
        renamed=row([10,20],"another")
        b=row([12,22])
        self.assertEqual(a["arrays"],renamed["arrays"])
        self.assertNotEqual(a["figure"],renamed["figure"])
        self.assertNotEqual(a["arrays"],b["arrays"])
        self.assertNotEqual(a["complete"],row([10,20],unit="K")["complete"])

    def test_absent_arrays_fail_closed(self):
        with self.assertRaises(ValueError):_row('{"data":[]}',{},"")
