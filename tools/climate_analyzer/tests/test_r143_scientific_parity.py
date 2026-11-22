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

    def test_report_capture_matches_selected_record_not_last(self):
        from unittest.mock import patch
        from epw_climate_analyzer.r143_scientific_parity import record_capture,CAPTURE_KEY
        raw='{"data":[{"x":[1],"y":[2]}],"layout":{}}'
        state={}
        items=[{"id":"selected","figure":raw,"context":{"source":"A"},"interpretation":"test"},
               {"id":"later","figure":raw,"context":{"source":"B"},"interpretation":"other"}]
        with patch("plotly.io.to_json",return_value=raw):
            record_capture(state,object(),{"source":"A"},"test","key",items,"selected")
            self.assertEqual(state[CAPTURE_KEY]["before"],state[CAPTURE_KEY]["saved"])
            self.assertEqual(state[CAPTURE_KEY]["sequence"],1)
            record_capture(state,object(),{"source":"A"},"test","key",items,"selected")
            self.assertEqual(state[CAPTURE_KEY]["sequence"],2)
            with self.assertRaises(AssertionError):
                record_capture(state,object(),{},"","key",items,"missing")
