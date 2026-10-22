"""One native SH -> native N320 -> hybrid hydrostatic processing chain."""
from __future__ import annotations
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
from p9_3b3_compare_pressure import hydrostatic_pressure
from p9_3b3_compare_vertical_frame import G0,PressureSeries,SourceBlocked,VerticalCoordinate,fingerprint
from p9_3b3_native_sources import GaussianGrid,NativeSource,original_surface_grib,synthesize,verify_grib_copy
from p9_3b3_reference_column import hybrid_column,transfer_pressure
from p9_3b3_reference_run import distance_km


class NativeColumns:
    def __init__(self,cache,protocol,heights):
        self.cache,self.protocol,self.heights=cache,protocol,heights
        self.surface,self.temperature,self.moisture,self.reference=[NativeSource(protocol['source_base']+'/'+protocol[key],cache)
            for key in ('surface','temperature','moisture','grid_reference')]
        t=self.temperature.array('t')[1];q=self.moisture.array('q')[1];pv=t.get('GRIB_pv')
        if not isinstance(pv,list) or len(pv)!=276 or q.get('GRIB_pv')!=pv:raise ValueError('P93N_NATIVE_T_Q_HYBRID_COEFFICIENTS_DIFFER')
        if any(self.surface.array(name)[1].get('GRIB_pv')!=pv for name in ('z','lnsp')):
            raise ValueError('P93N_NATIVE_SURFACE_T_Q_HYBRID_COEFFICIENTS_DIFFER')
        self.A,self.B=pv[:138],pv[138:]
        for source,name,units,param,grid in ((self.surface,'z','m**2 s**-2',129,'sh'),(self.surface,'lnsp','~',152,'sh'),
                (self.temperature,'t','K',130,'sh'),(self.moisture,'q','kg kg**-1',133,'reduced_gg')):
            a,b=source.array(name)
            if (b.get('units')!=units or b.get('GRIB_paramId')!=param or b.get('GRIB_gridType')!=grid or
                    b.get('GRIB_stepType')!='instant' or b.get('GRIB_typeOfLevel')!='hybrid'):
                raise ValueError('P93N_NATIVE_FIELD_SEMANTICS:'+name)
            if grid=='sh' and tuple(b.get('GRIB_'+k) for k in ('J','K','M'))!=(639,639,639):raise ValueError('P93N_SPECTRAL_TRUNCATION_MISMATCH')
        lat=self.moisture._vector('latitude');lon=self.moisture._vector('longitude');self.grid=GaussianGrid(lat,lon)
        if len(lat)!=542080 or len(self.grid.rings)!=640 or q.get('GRIB_N')!=320:raise ValueError('P93N_EXPECTED_NATIVE_REDUCED_N320_GRID')
        if not np.array_equal(lat,self.reference._vector('latitude')) or not np.array_equal(lon,self.reference._vector('longitude')):
            raise ValueError('P93N_INDEPENDENT_GRID_REFERENCE_COORDINATES_DIFFER')
        self.by_country={country:self.grid.neighbors(h['sensors']['pressure']['latitude'],h['sensors']['pressure']['longitude'])
            for country,h in heights.items() if h['status']!='SOURCE_BLOCKED'}
        if not self.by_country:raise SourceBlocked('P93N_NO_HISTORICAL_PRESSURE_TARGETS')
        self.indices=sorted({j for js in self.by_country.values() for j in js});self.points=self.grid.points(self.indices)
        self.manifest={'sources':{key:{'url':s.base,'metadata_sha256':s.metadata_sha}
            for key,s in (('surface',self.surface),('temperature',self.temperature),('moisture',self.moisture),('grid_reference',self.reference))},
            'native_grid':'REDUCED_GAUSSIAN_N320','spectral_synthesis':'T639_TO_NATIVE_N320_SHTOOLS_REAL_4PI_NO_CS',
            'GRIB_pv_sha256':fingerprint(pv),'source_points':self.points,'original_GRIB_controls':[],
            'independent_GG_diagnostics':[],'native_future_CanESM5_pressure_recovered':False,'T_q_GRIB_byte_identity':'NOT_CHECKED_OR_CLAIMED'}

    def controls(self):
        for stamp in self.protocol['source_control_hours']:
            for name,param in (('z',129),('lnsp',152)):
                path=self.protocol['original_surface_GRIB'].format(month=stamp[:7].replace('-',''),variable='zs' if name=='z' else 'lnsp')
                raw,meta=original_surface_grib(self.cache,self.protocol['source_base']+'/'+path,stamp,param)
                if meta['hybrid_pv_sha256']!=self.manifest['GRIB_pv_sha256']:
                    raise ValueError('P93N_ORIGINAL_GRIB_T_Q_HYBRID_COEFFICIENTS_DIFFER')
                copy=self.surface.field(name,stamp)
                self.manifest['original_GRIB_controls'].append({'timestamp_UTC':stamp,'variable':name,**meta,**verify_grib_copy(raw,copy)})
            z=synthesize(self.surface.field('z',stamp),self.points);lnsp=synthesize(self.surface.field('lnsp',stamp),self.points)
            zg=self.reference.field('z',stamp)[self.indices];all_pg=self.reference.field('sp',stamp);pg=all_pg[self.indices]
            self.manifest['independent_GG_diagnostics'].append({'timestamp_UTC':stamp,
                'max_abs_geopotential_height_delta_m':float(np.max(abs(z-zg))/G0),
                'max_abs_surface_pressure_delta_Pa':float(np.max(abs(np.exp(lnsp)-pg))),
                'status':'CROSS_ENCODING_DIAGNOSTIC_NOT_STATION_ACCURACY_OR_FITTED_SOURCE_GATE',
                'source_GG_pressure_min_distinct_increment_Pa':float(np.min(np.diff(np.unique(all_pg.astype(float))))),'correction_applied':False})
        self.manifest['paired_surface_lineage_status']='ORIGINAL_GRIB_TO_CO_CAST_IDENTITY_CONFIRMED_AT_BOTH_CONTROL_HOURS'
        return self.manifest

    def read(self,stamp,first_level):
        levels=list(range(first_level,138));self.temperature.levels(levels);self.moisture.levels(levels)
        z=synthesize(self.surface.field('z',stamp),self.points);lnsp=synthesize(self.surface.field('lnsp',stamp),self.points)
        # Read independent chunks concurrently, with shared byte reservations.
        # SHTOOLS point synthesis stays on this thread: its Fortran workspace
        # is not assumed thread safe.
        self.temperature.time_index(stamp);self.moisture.time_index(stamp)
        vectors={}
        with ThreadPoolExecutor(max_workers=6) as pool:
            jobs={pool.submit(source.field,name,stamp,k):(name,k)
                  for source,name in ((self.temperature,'t'),(self.moisture,'q')) for k in levels}
            for task in as_completed(jobs):
                name,k=jobs[task];v=task.result()
                vectors[name,k]=synthesize(v,self.points) if name=='t' else v[self.indices]
        temp=np.column_stack([vectors['t',k] for k in levels]);q=np.column_stack([vectors['q',k] for k in levels]);columns={}
        for i,(lat,lon) in enumerate(self.points):
            data={'stamp':stamp,'latitude':lat,'longitude':lon,'first_level':first_level,'z':float(z[i]),'lnsp':float(lnsp[i]),
                'T':temp[i].tolist(),'q':q[i].tolist(),'source_manifest':self.manifest['sources'],'hybrid_pv':self.manifest['GRIB_pv_sha256']}
            columns[self.indices[i]]=hybrid_column(lnsp[i],z[i],temp[i],q[i],self.A,self.B,first_level=first_level,
                timestamp_UTC=stamp,latitude=lat,longitude=lon,source='ERA5_ORIGINAL_SH_CO_TO_NATIVE_N320_HYBRID_COLUMN',source_sha256=fingerprint(data))
        return columns

    def predict(self,columns,stamp):
        result={}
        for country in self.protocol['countries']:
            sensor=self.heights[country].get('sensors',{}).get('pressure')
            methods={name:{'status':'SOURCE_BLOCKED'} for name in self.protocol['methods']}
            if sensor is None:
                result[country]={'methods':{n:{**v,'reason':'HISTORICAL_PRESSURE_SENSOR_REFERENCE_UNAVAILABLE'} for n,v in methods.items()}};continue
            cs=[columns[j] for j in self.by_country[country]]
            ds=[distance_km(sensor['latitude'],sensor['longitude'],c.latitude,c.longitude) for c in cs]
            target=VerticalCoordinate(sensor['height_MSL_m'],'GEOPOTENTIAL_HEIGHT_M','MSL_GEOID','BAROMETER',
                'WMDR_DATED_INSTRUMENT_MSL_APPROX_H:'+sensor['source_sha256'],True);phi=G0*target.value
            eligible=[(c,d) for c,d in zip(cs,ds) if c.domain[0]<=phi<=c.domain[1]]
            geometry=[{'latitude':c.latitude,'longitude':c.longitude,'distance_km':d,'surface_H_m':c.domain[0]/G0,
                'top_H_m':c.domain[1]/G0,'column_fingerprint':c.fingerprint} for c,d in zip(cs,ds)]
            if not eligible:
                why='NO_NATIVE_NEIGHBOR_AIR_DOMAIN_COVERS_BAROMETER_NO_UNDERGROUND_EXTRAPOLATION'
                result[country]={'methods':{n:{**v,'reason':why} for n,v in methods.items()},'geometry':geometry,'target':asdict(target)};continue
            closest,d=min(eligible,key=lambda pair:(pair[1],pair[0].latitude,pair[0].longitude))
            for name,cols,dist in (('P2_NATIVE_SINGLE_COLUMN',[closest],[d]),('P2_NATIVE_UP_TO_FOUR_COLUMNS',cs,ds)):
                try:
                    value=transfer_pressure(cols,dist,target,timestamp_UTC=stamp)
                    methods[name]={'status':'CONDITIONAL_NATIVE_HYDROSTATIC_RESULT','pressure_Pa':value['pressure_Pa'],
                        'target_layer_T_K':value['target_layer_T_K'],'target_layer_q_kgkg':value['target_layer_q_kgkg'],
                        'anchor_phi_m2s2':value['anchor_phi_m2s2'],'active_columns':value['active_columns'],
                        'independent_accuracy':'NOT_QUALIFIED','datum_approximation':'H_EQUALS_NATIONAL_MSL_HEIGHT_CONSTANT_G0'}
                except SourceBlocked as exc:methods[name]={'status':'SOURCE_BLOCKED','reason':str(exc)}
            t,qq=closest.state(phi)
            anchor=VerticalCoordinate(closest.domain[0]/G0,'GEOPOTENTIAL_HEIGHT_M','MSL_GEOID','GRID_SURFACE','NATIVE_SURFACE_PHI_G0',True)
            p=PressureSeries((closest.half_pressure_Pa[-1],),anchor,stamp[:10],closest.source,
                'INSTANTANEOUS_UTC_NODE:'+stamp,source_sha256=closest.source_sha256)
            for method,lapse in (('P1_ISOTHERMAL_SAME_SINGLE_ANCHOR',0.),('P1_FIXED_LAPSE_0.0065_SAME_SINGLE_ANCHOR',.0065)):
                value=hydrostatic_pressure(p,target,[t],[qq],proxy_source=closest.source+'|'+stamp,proxy_date=stamp[:10],lapse_K_per_m=lapse)
                methods[method]={'status':'CONDITIONAL_DECLARED_COLUMN_RESULT','pressure_Pa':value.pressure.values_Pa[0],
                    'source_column_fingerprint':closest.fingerprint,'lapse_K_m':lapse,'independent_accuracy':'NOT_QUALIFIED'}
            result[country]={'methods':methods,'geometry':geometry,'target':asdict(target)}
        return result
