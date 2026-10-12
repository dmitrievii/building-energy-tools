"""Public fixture mathematical contracts; commercial source only in local optional tests."""
import unittest,csv,io,copy,hashlib,importlib.util
from pathlib import Path
SRC=Path(__file__).parent/'p7c5b_solar_illuminance.py'
spec=importlib.util.spec_from_file_location('p7c5b_solar_illuminance',SRC)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def fixture():
    hdr=[['LOCATION','Graz','-', '-', 'TEST','0000','46.983','15.45','1','342']]+[['DATA']]*7
    base=[];fut=[]
    from datetime import date,timedelta
    for d in range(365):
        day=date(2005,1,1)+timedelta(days=d)
        for hour in range(1,25):
            r=['2005',str(day.month),str(day.day),str(hour),'60','test','15','7','65','98000','0','0','300','0','0','0','0','0','0','9999','180','2','5','4','9999','99999','9','999999999','10','0.15','0','0','0.1','0','99']
            ff=r.copy()
            if 8<=hour<=17:
                r[13:19]=['400','500','150','43100','46500','19000'] # baseline source gl approx 19k + 46.5k*0.5
                ff[13:16]=['520','600','220'] # cos=.5
            base.append(r);fut.append(ff)
    return m.encode_epw(hdr,base),m.encode_epw(hdr,fut)

class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.base,cls.future=fixture()
    def generate(self,base=None,future=None,bs=None,fs=None):
        b=base if base is not None else self.base
        f=future if future is not None else self.future
        return m.corrected_illuminance(b,f,bs or m.sha(b),fs or m.sha(f))
    def test_authentic_source_hash_guard(self):
        with self.assertRaisesRegex(ValueError,'Baseline EPW source SHA'):
            self.generate(bs='0'*64)
    def test_future_member_hash_guard(self):
        with self.assertRaisesRegex(ValueError,'P7C.4 source SHA'):
            self.generate(fs='0'*64)
    def test_new_illuminance_physical_closure(self):
        raw,a=self.generate();h,rr=m.parse_epw(raw)
        self.assertEqual(len(rr),8760)
        self.assertTrue(a['changed_hour_count']>3500)
        self.assertLessEqual(a['photometric_closure_residual_max_lux'],0.51)
        for r in rr:
            if float(r[13])>0:
                proj=(float(r[13])-float(r[15]))/float(r[14])
                self.assertAlmostEqual(float(r[16]),float(r[18])+float(r[17])*proj,delta=.51)
    def test_thermodynamics_solar_and_wind_invariant(self):
        raw,a=self.generate();_,rr=m.parse_epw(raw);_,fr=m.parse_epw(self.future)
        for x,y in zip(rr,fr):
            self.assertEqual([v for j,v in enumerate(x) if j not in m.ILLUMINANCE_FIELDS],
                             [v for j,v in enumerate(y) if j not in m.ILLUMINANCE_FIELDS])
    def test_zenith_missing_preserved(self):
        raw,a=self.generate();_,rr=m.parse_epw(raw)
        self.assertTrue(all(row[19]=='9999' for row in rr))
    def test_both_zero_night_unchanged(self):
        raw,a=self.generate();_,rr=m.parse_epw(raw)
        self.assertEqual(rr[0][16:19],['0','0','0'])
    def test_illuminance_nonnegative(self):
        raw,a=self.generate();_,rr=m.parse_epw(raw)
        self.assertTrue(all(float(x)>=0 for r in rr for x in r[16:19]))
    def test_no_fabricated_daylight_qualification(self):
        raw,a=self.generate()
        self.assertFalse(a['production_daylight_qualified'])
    def test_infeasible_radiation_rejected(self):
        _,rr=m.parse_epw(self.future);h,_=m.parse_epw(self.future)
        rr[9][15]='800'
        with self.assertRaisesRegex(ValueError,'diffuse exceeds global'):
            self.generate(future=m.encode_epw(h,rr))
    def test_broken_epw_rejected(self):
        with self.assertRaisesRegex(ValueError,'8760'):
            self.generate(future=self.future[:200])
    def test_roundtrip_unchanged_fields_and_epw_35_columns(self):
        raw,a=self.generate();_,rows=m.parse_epw(raw)
        self.assertTrue(all(len(row)==35 for row in rows))
    def test_reproducibility_byte_identical(self):
        a,_=self.generate();b,_=self.generate();self.assertEqual(m.sha(a),m.sha(b))
    def test_high_diffuse_without_beam(self):
        hdr,br=m.parse_epw(self.base);_,fr=m.parse_epw(self.future)
        for row in [br[10],fr[10]]:row[13]='200';row[14]='0';row[15]='200'
        bs=m.encode_epw(hdr,br);fs=m.encode_epw(hdr,fr)
        raw,a=self.generate(base=bs,future=fs)
        _,rr=m.parse_epw(raw)
        self.assertEqual(rr[10][16],rr[10][18])
    def test_source_twilight_lux_retained(self):
        h,br=m.parse_epw(self.base);_,fr=m.parse_epw(self.future)
        for row in [br[0],fr[0]]:row[16]='11';row[17]='0';row[18]='11'
        bs=m.encode_epw(h,br);fs=m.encode_epw(h,fr)
        raw,a=self.generate(base=bs,future=fs);_,rr=m.parse_epw(raw)
        self.assertEqual(rr[0][16],'11');self.assertEqual(a['source_twilight_positive_lux_hours_preserved'],1)

if __name__=='__main__':unittest.main()