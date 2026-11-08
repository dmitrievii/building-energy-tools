"""Same calendar grid and joint donor support for the paired comparison."""
import collections
import copy
import numpy as np
from ige_auto.cases import Cases
from ige_auto.data import buck_water
from ige_local.common import digest
from .physics import q_from_e


class HumidityCases:
    def __init__(self,cube,c,panels,donors,label):
        b=Cases(cube,panels,donors,"RH",c,label);self.base=b
        if cube.meta["variables"][:3]!=["T","RH","p"]:
            raise ValueError("Native cube variables T/RH/p required")
        self.values=np.asarray(cube.values[b.s,b.t,:3]).copy()
        self.eligible=np.asarray(cube.eligible[b.s,b.t,:3])&np.isfinite(self.values)
        self.dvalues=np.asarray(cube.values[b.d[None,:],b.t[:,None],:3]).copy()
        dop=np.asarray(cube.operators[b.d[None,:],b.t[:,None],:3])
        op=np.asarray(cube.operators[b.s,b.t,:3])
        self.quality=(np.asarray(cube.eligible[b.d[None,:],b.t[:,None],:3])
                      &np.isfinite(self.dvalues)&(dop==op[:,None,:])&(dop!=0))
        self.target_qc=np.asarray(cube.qc[b.s,b.t,:3])
        self.donor_qc=np.asarray(cube.qc[b.d[None,:],b.t[:,None],:3])
        self.geometry=np.zeros(b.mask.shape,dtype=bool)
        self.families=collections.defaultdict(list)
        for j,d in enumerate(b.d):self.families[cube.stations[d]["family"]].append(j)
        for i,s in enumerate(b.s):
            st=cube.stations[s]
            self.geometry[i]=[cube.stations[d]["country"]==st["country"] and
                              cube.stations[d]["family"]!=st["family"] for d in b.d]
        self.geometry &= b.dist>max(c["co_location_km"],1e-9)
        self.e=self.values[:,1]*buck_water(self.values[:,0])/100
        self.de=self.dvalues[:,:,1]*buck_water(self.dvalues[:,:,0])/100
        self.q=q_from_e(self.e,self.values[:,2]);self.dq=q_from_e(self.de,self.dvalues[:,:,2])
        self.joint_reference=(self.eligible.all(axis=1)&(self.values[:,0]>-273.15)&
                              np.isfinite(self.e)&(self.e>0)&(self.e<self.values[:,2]))
        self.joint_donors=(self.quality.all(axis=2)&(self.dvalues[:,:,0]>-273.15)&
                           np.isfinite(self.de)&(self.de>0)&(self.de<self.dvalues[:,:,2]))
        self.cohort_id=digest({"rows":b.row_id,"donors":[cube.stations[d]["key"] for d in b.d],
                               "protocol":"joint_TRHp_positive_vapour_source_contract"})

    def view(self,coordinate,paired=True):
        b=copy.copy(self.base);b.variable=coordinate
        if paired:
            obs=self.joint_reference.copy();mask=self.joint_donors.copy()
        elif coordinate=="RH":
            obs=self.eligible[:,1].copy();mask=self.quality[:,:,1].copy()
        else:
            obs=self.eligible[:,:2].all(axis=1)&np.isfinite(self.e)&(self.e>0)&(self.values[:,0]>-273.15)
            mask=self.quality[:,:,:2].all(axis=2)&np.isfinite(self.de)&(self.de>0)&(self.dvalues[:,:,0]>-273.15)
            if coordinate=="q":obs &= self.joint_reference;mask &= self.joint_donors
        if coordinate=="RH":y,dv=self.values[:,1],self.dvalues[:,:,1]
        elif coordinate=="log_e":
            with np.errstate(divide="ignore",invalid="ignore"):y,dv=np.log(self.e),np.log(self.de)
        elif coordinate=="q":y,dv=self.q,self.dq
        else:raise ValueError("Unknown coordinate")
        mask &= self.geometry&np.isfinite(dv)
        for cols in self.families.values():
            if len(cols)>1:
                chosen=np.argmin(np.where(mask[:,cols],b.dist[:,cols],np.inf),axis=1)
                for j,col in enumerate(cols):mask[:,col]&=chosen==j
        b.y=np.asarray(y).copy();b.obs=obs&np.isfinite(b.y)
        b.mask=mask;b.dv=np.where(mask,dv,0.)
        b.n_donors=mask.sum(axis=1);b.ready=b.n_donors>=2;b.fit_mask=b.obs&b.ready
        b.case_id=digest({"cohort_id":self.cohort_id,"coordinate":coordinate,"paired":paired})
        b.ledger=b.ledger|{"case_id":b.case_id,"cohort_id":self.cohort_id,"coordinate":coordinate,
            "support":"joint_TRHp" if paired else "own_required_variables",
            "target_observed":int(b.obs.sum()),"donor_ready_all_calendar":int(b.ready.sum()),"scorable":int(b.fit_mask.sum())}
        return b

    def common_mask(self,aux):
        b=self.view("RH")
        t,p=aux["T"],aux["p"]
        es=buck_water(t)
        return b.fit_mask&np.isfinite(t)&(t>-273.15)&np.isfinite(p)&(p>0)&np.isfinite(es)&(es>0)
