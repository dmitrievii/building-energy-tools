"""Create clearly labeled synthetic, non-certifying demo ZIP for the UI."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import json
import math
import zipfile
import numpy as np
import pandas as pd


def build(path: Path):
    n=8760
    frames=[]
    for z,amp,base in [('OFFICE-A',820,20.3),('OFFICE-B',1100,22.1)]:
        h=np.arange(n,dtype=int)
        daily=np.sin(2*np.pi*(h%24)/24)
        seasonal=np.cos(2*np.pi*h/n)
        signed=(600*seasonal + amp*daily).round(3)
        temp=base+2.7*daily-1.0*seasonal
        rh=49+12*np.sin(2*np.pi*(h%24)/24+1)
        frames.append(pd.DataFrame({
            'zone_id':z,'hour_index':h+1,'signed_load_w':signed,
            'heating_load_w':np.maximum(signed,0), 'cooling_load_w':np.maximum(-signed,0),
            'operative_temp_c':temp+0.2,'air_temp_c':temp,'radiant_temp_c':temp+0.4,
            'solar_gain_w':np.maximum(0,amp*daily), 'rh_pct':rh,
        }))
    hourly=pd.concat(frames,ignore_index=True)
    monthly=[]
    for zone,g in hourly.groupby('zone_id'):
        g=g.copy();g['month']=pd.date_range('2001-01-01',periods=n,freq='h').month
        for mo,period in g.groupby('month'):
            monthly.append(dict(zone_id=zone,month=mo,heating_need_kwh=period.heating_load_w.sum()/1000,
                                cooling_need_kwh=period.cooling_load_w.sum()/1000))
    month=pd.DataFrame(monthly)
    metrics=[]
    for mo,p in month.groupby('month'):
        metrics.append(('DEMO','HWB','kWh',mo,round(p.heating_need_kwh.sum(),3)))
        metrics.append(('DEMO','KB','kWh',mo,round(p.cooling_need_kwh.sum(),3)))
    metric_df=pd.DataFrame(metrics,columns=['scenario','metric','unit','month','value'])
    trace=pd.DataFrame([dict(step=i,timestamp=str(pd.Timestamp('2001-01-01')+pd.Timedelta(hours=i))+'+00:00',
                             period_label='',initialization=False,category='ventilation',quantity='co2_ppm',
                             scope='Zone',zone_id='OFFICE-A',object_id='',node_index='',
                             numeric_value=550+200*math.sin(2*math.pi*(i%24)/24)**2,text_value='',unit='ppm')
                        for i in range(n)])
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        z.writestr('manifest.json',json.dumps({'release':'SYNTHETIC DEMO - NOT AN EPB RESULT',
            'calculationFingerprint':'DEMO_ONLY','isComplete':False,'calculationProfileId':'SYNTHETIC'},indent=2))
        z.writestr('visualization/manifest.json',json.dumps({'schema_version':1,'has_hourly_thermal':True,
             'has_validation_trace':True,'time_basis':'Synthetic reference year for UI testing only'},indent=2))
        z.writestr('visualization/hourly-thermal.csv',hourly.to_csv(index=False))
        z.writestr('visualization/monthly-thermal.csv',month.to_csv(index=False))
        z.writestr('visualization/zone-metadata.json',json.dumps({x:{'zoneId':x} for x in hourly.zone_id.unique()}))
        z.writestr('visualization/validation-trace.csv',trace.to_csv(index=False))
        z.writestr('monthly-metrics.csv',metric_df.to_csv(index=False))
        z.writestr('scenario-summary.csv','scenario,is_complete,automatic_compliance,hwb\nDEMO,false,false,0\n')
        z.writestr('carrier-ledger.csv','scenario,path,carrier,use,is_export,source_id,month,value_kwh\nDEMO,demo,Electricity,Heating,false,demo-system,1,21\n')

if __name__=='__main__':
    p=Path(__file__).resolve().parents[1]/'SYNTHETIC_DEMO_NOT_CERTIFICATION.zip'
    build(p)
    print(p)
