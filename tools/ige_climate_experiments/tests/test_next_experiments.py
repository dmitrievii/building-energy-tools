"""Physical transfer identities, leakage barriers, fixed masks and source preservation."""
import contextlib
import copy
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from support_auto import ROOT,config,synthetic_cube,save_cube
from ige_auto.cases import Cases
from ige_auto.fit import fit_cases
from ige_hum.auxiliary import MODEL
from ige_hum.config import sealed
from ige_hum.physics import dewpoint_water
from ige_hum.study import seal
from ige_local.common import InputError,digest,file_hash,read_json,write_json
from ige_next.cases import Moisture,meteo,pressure_physics,restore,background_features
from ige_next.config import load,matrix,TEMPERATURE,PRESSURE,MOISTURE
from ige_next.engine import fit,predict,search
from ige_next.study import prepare,check_run,train,validate_bundle,resume,path_for,guard_C


class NextWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.c=config(self.base);self.c["variables"]=["T","RH","p","log_e_water"]
        self.cube=synthetic_cube(self.base,self.c,missing=True)
        self.d=np.flatnonzero(self.cube.roles=="D");self.v=np.flatnonzero(self.cube.roles=="V")
        self.dt=np.flatnonzero(self.cube.time_roles=="D");self.vt=np.flatnonzero(self.cube.time_roles=="V")
        self.panels=[(self.v,self.vt)]

    def moisture(self,support="joint"):
        return Moisture(self.cube,self.c,self.panels,self.d,"test",support)

    def aux(self,native):
        return {"T":native.values[:,0].copy(),"p":native.values[:,2].copy()}

    def source(self):
        source=self.base/"source";shutil.copytree(self.cube.path,source/"cube")
        anchor={k:self.cube.meta[k] for k in ("data_signature","family_roles","inner_folds","times","time_roles","stations")}
        anchor["schema"]="IGE_AUTO_SPLIT_v1";anchor["split_id"]=digest(anchor)
        spec=seal(source/"run_spec.sealed.json",{"cube_id":self.cube.meta["cube_id"],"base_configuration":self.c,"anchor":anchor,
            "configuration":{"cohort_anchor":str(self.base/"detached/cube/split.sealed.json")}},"spec_id")
        write_json(source/"summary.json",{"holdout_opened":False,"exit_code":0})
        for name in ["aux_full_D"]+["aux_inner_"+str(f) for f in range(self.c["inner_folds"])]:
            ix=self.d if name=="aux_full_D" else np.flatnonzero((self.cube.roles=="D")&(self.cube.folds!=int(name[-1])))
            value={}
            for var in ("T","p"):
                a=Cases(self.cube,[(ix,self.dt)],ix,var,self.c,name)
                value[var]={"model":MODEL,"optimization":{"status":"CONVERGED","eta":[2.,0.]},
                    "fit":fit_cases(a,MODEL,[2.,0.],self.c["optimizer"]),
                    "training_families":sorted({self.cube.stations[i]["family"] for i in ix}),"training_years":self.c["years"]["D"]}
            seal(source/"checkpoints"/(name+".json"),{"spec_id":spec["spec_id"],"value":value},"checkpoint_id")
        return source

    def config_next(self,source):
        x=read_json(ROOT/"config_interpolation_v030.json")
        x.update(source_run=str(source),results=str(self.base/"new_results"),optimizer=self.c["optimizer"])
        p=self.base/"next.json";write_json(p,x);return load(p)


class NewPhysics(NextWorkspace):
    def test_Td_and_deficit_roundtrip(self):
        n=self.moisture();ax=self.aux(n)
        for co in ("Td","D"):
            v=n.view(co);p=restore(co,v.y,ax);use=v.obs
            np.testing.assert_allclose(p["RH"][use],n.values[use,1],atol=1e-9)

    def test_deficit_forecast_uses_predicted_temperature(self):
        a=restore("D",np.array([4.]),{"T":np.array([5.]),"p":np.array([950.])})
        b=restore("D",np.array([4.]),{"T":np.array([25.]),"p":np.array([950.])})
        self.assertNotAlmostEqual(a["RH"][0],b["RH"][0])
        self.assertEqual(a["Td_native_predicted"][0],1.)

    def test_negative_deficit_is_not_clipped(self):
        p=restore("D",np.array([-2.]),{"T":np.array([10.]),"p":np.array([1000.])})
        self.assertGreater(p["RH"][0],100.);self.assertTrue(p["supersaturated"][0])

    def test_support_changes_donors_not_calendar(self):
        n=self.moisture();joint=n.view("RH",True);own=n.view("RH",False)
        self.assertEqual(joint.row_id,own.row_id)
        self.assertTrue(np.all(own.n_donors>=joint.n_donors));self.assertTrue(np.any(own.n_donors>joint.n_donors))

    def test_own_q_scoring_can_have_RH_without_target_pressure(self):
        from ige_hum.metrics import score
        n=self.moisture("own");n.eligible[0,2]=False;n.joint_reference[0]=False
        ax={"T":np.full(len(n.values),15.),"p":np.full(len(n.values),950.)}
        p=restore("q",np.full(len(n.values),.005),ax)
        sc=score(n,p,n.eligible[:,1]);self.assertEqual(sc["RH"]["N_scored"],int(n.eligible[:,1].sum()))
        self.assertLess(sc["q_kgkg"]["N_scored"],sc["RH"]["N_scored"])

    def test_common_mask_independent_of_coordinate_and_support(self):
        n=self.moisture();ax=self.aux(n);mask=n.common_mask(ax)
        for support in ("joint","own"):
            other=self.moisture(support)
            np.testing.assert_array_equal(other.common_mask(ax),mask)
            for co in ("RH","log_e","q","Td","D"):self.assertTrue(np.all(other.view(co).fit_mask[mask]))

    def test_joint_domain_excludes_uninvertible_dewpoint_for_every_coordinate(self):
        arrays={k:np.asarray(getattr(self.cube,k)).copy() for k in ("values","eligible","operators","qc","sources")}
        arrays["values"][self.d[0],:,:3]=[15.,1e-12,950.];arrays["eligible"][self.d[0],:,:3]=True
        changed=save_cube(self.base/"extreme_vapour",self.cube.meta,arrays)
        n=Moisture(changed,self.c,self.panels,self.d,"domain","joint")
        self.assertTrue(np.all(np.isnan(n.dtd[:,0])));self.assertFalse(n.joint_donors[:,0].any())
        masks=[n.view(co,True).mask for co in ("RH","log_e","q","Td","D")]
        for m in masks[1:]:np.testing.assert_array_equal(m,masks[0])

    def test_copied_auxiliary_tamper_cannot_enter_another_fit(self):
        source=self.source()
        with contextlib.redirect_stdout(io.StringIO()):out=prepare(self.config_next(source))
        p=out/"auxiliary/aux_full_D.json";cp=sealed(p,"checkpoint_id");cp.pop("checkpoint_id")
        cp["value"]["T"]["fit"]["coefficients"]=[999.];seal(p,cp,"checkpoint_id")
        with self.assertRaisesRegex(InputError,"Copied auxiliary changed"):check_run(out)

    def test_local_gradient_uses_only_donor_values(self):
        a=meteo(self.cube,self.c,self.panels,self.d,"T","test")
        m=next(m for m in TEMPERATURE if m["basis"]=="local_height");eta=[2.,0.,-4.]
        fitted={"coefficients":[-6.]};before=predict(a,m,eta,fitted)[0]
        a.y[:]=10000;after=predict(a,m,eta,fitted)[0]
        np.testing.assert_array_equal(before,after)

    def test_hinge_is_continuous_in_height_knot(self):
        a=meteo(self.cube,self.c,self.panels,self.d,"T","test")
        x=a.design("hinge","idw",[2.,0.,-5.,.8])[1]
        z=a.design("hinge","idw",[2.,0.,-5.,.800001])[1]
        self.assertLess(np.max(abs(x-z)),2e-6)

    def test_diurnal_features_use_target_and_donor_longitudes(self):
        a=meteo(self.cube,self.c,self.panels,self.d,"T","test");base,x,w=a.design("diurnal","idw",[2.,0.,-5.])
        expected=a.zt*np.sin(a.ht)-np.sum(w*a.zd[None,:]*np.sin(a.hd),axis=1)
        np.testing.assert_allclose(x[:,3],expected)
        self.assertGreater(np.ptp(a.hd[0]),0.)

    def test_local_gradient_recovers_linear_synthetic_field(self):
        a=meteo(self.cube,self.c,self.panels,self.d,"T","test")
        m=next(m for m in TEMPERATURE if m["basis"]=="local_height");eta=[2.,0.,-4.]
        fitted=fit(a,m,eta,self.c["optimizer"]);p,_=predict(a,m,eta,fitted)
        np.testing.assert_allclose(fitted["coefficients"],[-7.3],atol=1e-8)
        self.assertLess(float(np.mean(abs(p[a.fit_mask]-a.y[a.fit_mask]))),1e-8)

    def test_pressure_vertical_direction_and_units(self):
        n=self.moisture();ax={"T":np.full(len(n.values),15.),"p":np.full(len(n.values),950.)}
        a=pressure_physics(self.cube,self.c,self.panels,self.d,ax,"p")
        raw=np.asarray(self.cube.values[a.d[None,:],a.t[:,None],2]);use=a.mask&(a.dz>0)
        self.assertTrue(use.any());self.assertTrue(np.all(a.physical_donors[use]<raw[use]))
        n0=np.flatnonzero(a.mask.ravel())[0];i,j=np.unravel_index(n0,a.mask.shape)
        tv=((n.dvalues[i,j,0]+15+546.3)/2)*(1+.61*n.dq[i,j])
        expected=raw[i,j]*np.exp(-9.80665*1000*a.dz[i,j]/(287.05*tv))
        self.assertAlmostEqual(a.physical_donors[i,j],expected)

    def test_pressure_does_not_use_target_observed_T_or_RH(self):
        n=self.moisture();ax={"T":np.full(len(n.values),15.),"p":np.full(len(n.values),950.)}
        a=pressure_physics(self.cube,self.c,self.panels,self.d,ax,"p")
        arrays={k:np.asarray(getattr(self.cube,k)).copy() for k in ("values","eligible","operators","qc","sources")}
        arrays["values"][self.v,:,:2]=999.
        changed=save_cube(self.base/"changed",self.cube.meta,arrays)
        b=pressure_physics(changed,self.c,self.panels,self.d,ax,"p")
        np.testing.assert_array_equal(a.physical_donors,b.physical_donors)

    def test_no_correction_reference_has_no_spurious_coefficients(self):
        a=meteo(self.cube,self.c,self.panels,self.d,"T","test");m=TEMPERATURE[1]
        fitted=fit(a,m,[2.,0.],self.c["optimizer"]);self.assertEqual(fitted["coefficients"],[])
        p,w=predict(a,m,[2.,0.],fitted);np.testing.assert_allclose(p[a.ready],np.sum(w*a.dv,axis=1)[a.ready])


class FrozenProgram(NextWorkspace):
    def test_registered_matrix_has_all_73_candidates(self):
        c=read_json(ROOT/"config_interpolation_v030.json");rows=matrix(c)
        self.assertEqual(len(rows),73);self.assertEqual(sum(x["stage"]=="humidity" for x in rows),60)
        self.assertEqual(len({str(x) for x in rows}),73)

    def test_reject_invalid_config_and_windows_backslash(self):
        p=self.base/"bad.json";p.write_text('{"source_run":"E:\\User Folder"}',encoding="utf-8")
        with self.assertRaisesRegex(InputError,"Invalid JSON"):load(p)
        c=read_json(ROOT/"config_interpolation_v030.json");c["optimizer"]["starts"]=4;write_json(p,c)
        with self.assertRaisesRegex(InputError,"Invalid optimizer"):load(p)

    def test_prepare_preserves_source_and_never_reassigns_cohort(self):
        source=self.source();before={str(p):file_hash(p) for p in source.rglob('*') if p.is_file()}
        with contextlib.redirect_stdout(io.StringIO()):out=prepare(self.config_next(source))
        _,spec,cube=check_run(out)
        self.assertEqual(spec["cube_id"],self.cube.meta["cube_id"])
        self.assertEqual(spec["anchor"]["family_roles"],self.cube.meta["family_roles"])
        self.assertFalse(spec["protocol"]["C_evaluation_implemented"])
        self.assertEqual(before,{str(p):file_hash(p) for p in source.rglob('*') if p.is_file()})

    def test_changed_source_file_blocks_resume(self):
        source=self.source()
        with contextlib.redirect_stdout(io.StringIO()):out=prepare(self.config_next(source))
        write_json(source/"summary.json",{"changed":True})
        with self.assertRaisesRegex(InputError,"Source artifact changed"):check_run(out)

    def test_C_exposure_blocks_new_experiment(self):
        source=self.source();write_json(source/"C_OPENED.json",{})
        with self.assertRaisesRegex(InputError,"already exposed"):prepare(self.config_next(source))

    def test_auxiliary_must_exclude_check_families_and_years(self):
        source=self.source();value=sealed(source/"checkpoints/aux_full_D.json","checkpoint_id")["value"]
        value["T"]["training_years"].append(2025)
        with self.assertRaisesRegex(InputError,"families/years"):validate_bundle(value,self.cube,self.d,self.c)

    def test_program_resumes_and_prediction_tamper_is_rejected(self):
        source=self.source();cfg=self.config_next(source);cfg["stages"]=["T"]
        # End-to-end test of physical/data flow; no redundant repeated search of 73 models.
        with patch("ige_next.config.TEMPERATURE",TEMPERATURE[:3]),contextlib.redirect_stdout(io.StringIO()):
            out=prepare(cfg);first=train(out)
        self.assertEqual(first["models_eligible"],3);self.assertFalse(first["holdout_opened"])
        with patch("ige_next.study.search",side_effect=AssertionError("Completed candidates must be reused")),contextlib.redirect_stdout(io.StringIO()):second=train(out)
        self.assertEqual(second["best_per_group"],first["best_per_group"])
        p=next((out/"models").rglob("V_predictions.npz"));p.write_bytes(p.read_bytes()+b"tampered")
        with contextlib.redirect_stdout(io.StringIO()),self.assertRaisesRegex(InputError,"artifact changed"):train(out)

    def test_unobserved_C_values_cannot_change_D_or_V_cases(self):
        before=meteo(self.cube,self.c,self.panels,self.d,"T","test")
        arrays={k:np.asarray(getattr(self.cube,k)).copy() for k in ("values","eligible","operators","qc","sources")}
        sc=np.flatnonzero(self.cube.roles=="C");tc=np.flatnonzero(self.cube.time_roles=="C")
        arrays["values"][sc,:,:]+=1000;arrays["values"][:,tc,:]+=1000
        changed=save_cube(self.base/"C_changed",self.cube.meta,arrays)
        after=meteo(changed,self.c,self.panels,self.d,"T","test")
        for name in ("y","dv","mask","fit_mask"):np.testing.assert_array_equal(getattr(before,name),getattr(after,name))


if __name__=="__main__":unittest.main()
