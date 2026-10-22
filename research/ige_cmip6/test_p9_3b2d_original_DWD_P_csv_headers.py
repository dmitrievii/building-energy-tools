import csv,io,unittest
class NativeDWDPressureHeaderNormalization(unittest.TestCase):
 def test_original_header_with_spaces_comes_back_as_pressure_P(self):
  r=csv.DictReader(io.StringIO("STATIONS_ID;MESS_DATUM;QN_8;  P; P0  \n123;2020011000;10;994.2;1003.1\n"),delimiter=";")
  orig=list(r.fieldnames)
  r.fieldnames=[x.lstrip("\ufeff").strip() for x in orig]
  row=next(r)
  self.assertEqual(float(row["P"]),994.2)
  self.assertEqual(float(row["P0"]),1003.1)
  self.assertNotEqual(float(row["P"]),float(row["P0"]))
 def test_padded_BOM_header(self):
  r=csv.DictReader(io.StringIO("\ufeffSTATIONS_ID;MESS_DATUM;QN_8;  P; P0  \n123;2020011000;10;994.2;1003.1\n"),delimiter=";")
  r.fieldnames=[x.lstrip("\ufeff").strip() for x in r.fieldnames]
  self.assertEqual(next(r)["STATIONS_ID"],"123")
if __name__=="__main__":unittest.main()
