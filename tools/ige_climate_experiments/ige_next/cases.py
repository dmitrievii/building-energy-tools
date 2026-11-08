"""Own/joint humidity support and new temperature/pressure transfer operators."""
import copy
import numpy as np
from ige_auto.cases import Cases
from ige_auto.data import buck_water
from ige_hum.cases import HumidityCases
from ige_hum.physics import dewpoint_water,e_from_q,q_from_e
from ige_local.common import digest,InputError


class Moisture(HumidityCases):
    def __init__(self,cube,c,panels,donors,label,support):
        super().__init__(cube,c,panels,donors,label)
        self.support=support;self.td=dewpoint_water(self.e);self.dtd=dewpoint_water(self.de)
        # Paired coordinate tests must retain identical donor AND target domains.
        # Td's declared inverse domain is narrower than merely e>0.
        self.joint_reference &= np.isfinite(self.td)
        self.joint_donors &= np.isfinite(self.dtd)

    def view(self,coordinate,paired=None):
        paired=self.support=="joint" if paired is None else paired
        if coordinate not in {"Td","D"}:return super().view(coordinate,paired)
        b=super().view("log_e",paired)
        y=self.td if coordinate=="Td" else self.values[:,0]-self.td
        dv=self.dtd if coordinate=="Td" else self.dvalues[:,:,0]-self.dtd
        b.variable=coordinate;b.y=y.copy();b.obs &= np.isfinite(y)
        # Recompute the family selection after the derived-variable contract.
        mask=(self.joint_donors if paired else self.quality[:,:,:2].all(axis=2)&(self.de>0)).copy()
        mask &= self.geometry&np.isfinite(dv)
        for cols in self.families.values():
            if len(cols)>1:
                chosen=np.argmin(np.where(mask[:,cols],b.dist[:,cols],np.inf),axis=1)
                for j,col in enumerate(cols):mask[:,col]&=chosen==j
        b.mask=mask;b.dv=np.where(mask,dv,0.);b.n_donors=mask.sum(axis=1)
        b.ready=b.n_donors>=2;b.fit_mask=b.obs&b.ready
        b.case_id=digest({"cohort":self.cohort_id,"coordinate":coordinate,"support":self.support})
        b.ledger=b.ledger|{"case_id":b.case_id,"coordinate":coordinate,"support":self.support,
            "target_observed":int(b.obs.sum()),"scorable":int(b.fit_mask.sum())}
        return b

    def common_mask(self,aux):
        # Same fixed reference and donor contract for ALL coordinates/supports.
        b=super().view("RH",True)
        es=buck_water(aux["T"])
        return b.fit_mask&np.isfinite(self.td)&np.isfinite(aux["T"])&(aux["T"]>-273.15)&np.isfinite(es)&(es>0)&np.isfinite(aux["p"])&(aux["p"]>0)


def restore(coordinate,value,aux):
    from ige_hum.physics import restore as original
    if coordinate in {"RH","log_e","q"}:return original(coordinate,value,aux["T"],aux["p"])
    td=value if coordinate=="Td" else aux["T"]-value
    es=buck_water(td)
    with np.errstate(divide="ignore",invalid="ignore"):
        out=original("log_e",np.log(es),aux["T"],aux["p"])
    out["Td_native_predicted"]=td
    return out


def meteo(cube,c,panels,donors,variable,label):
    base=Cases(cube,panels,donors,variable,c,label)
    base.__class__=Transfer
    base.zt=np.array([cube.stations[s]["height_m"]/1000 for s in base.s])
    base.zd=np.array([cube.stations[d]["height_m"]/1000 for d in base.d])
    utc=np.array([int(cube.times[t][11:13])+int(cube.times[t][14:16])/60 for t in base.t])
    longitude=np.array([cube.stations[s]["lon"] for s in base.s])
    donor_lon=np.array([cube.stations[d]["lon"] for d in base.d])
    base.ht=2*np.pi*(utc+longitude/15)/24
    base.hd=2*np.pi*(utc[:,None]+donor_lon[None,:]/15)/24
    return base


class Transfer(Cases):
    def design(self,basis,kernel,eta):
        if basis not in {"none","nearest","diurnal","hinge","local_height","background","barometric","barometric_residual"}:
            return super().design(basis,kernel,eta)
        if basis=="nearest":
            chosen=np.argmin(np.where(self.mask,self.dist,np.inf),axis=1)
            w=np.zeros_like(self.dv);w[np.arange(len(chosen)),chosen]=1
            w[~self.mask.any(axis=1)]=0
        else:w=self.weights(kernel,eta)
        base=np.sum(w*self.dv,axis=1);z=np.sum(w*self.dz,axis=1)
        if basis in {"none","nearest"}:x=np.empty((len(z),0))
        elif basis in {"diurnal","background"}:
            sinz=self.zt*np.sin(self.ht)-np.sum(w*self.zd[None,:]*np.sin(self.hd),axis=1)
            cosz=self.zt*np.cos(self.ht)-np.sum(w*self.zd[None,:]*np.cos(self.hd),axis=1)
            x=np.column_stack((z,z*np.sin(self.phase),z*np.cos(self.phase),sinz,cosz))
        elif basis=="hinge":
            h=eta[3]
            hinge=np.maximum(self.zt-h,0)-np.sum(w*np.maximum(self.zd-h,0)[None,:],axis=1)
            x=np.column_stack((z,hinge))
        elif basis=="local_height":
            meanz=np.sum(w*self.zd[None,:],axis=1);meany=base
            centered=self.zd[None,:]-meanz[:,None]
            var=np.sum(w*centered*centered,axis=1)
            cov=np.sum(w*centered*(self.dv-meany[:,None]),axis=1)
            shrink=np.exp(eta[2]);den=var+shrink
            base=base+cov/den*z;x=(shrink/den*z)[:,None]
        else:
            base=np.sum(w*self.physical_donors,axis=1)
            x=z[:,None] if basis=="barometric_residual" else np.empty((len(z),0))
        return base,x,w


def pressure_physics(cube,c,panels,donors,aux,label):
    # Pressure physics requires q, without an unnecessary Td inverse-domain gate.
    native=HumidityCases(cube,c,panels,donors,label)
    b=meteo(cube,c,panels,donors,"p",label)
    joint=native.view("q",True)
    b.mask=joint.mask.copy();b.n_donors=b.mask.sum(axis=1);b.ready=b.n_donors>=2
    b.fit_mask=b.obs&b.ready&np.isfinite(aux["T"])
    # Assume a donor-specific q along the short vertical layer; target T is PREDICTED.
    layer=(native.dvalues[:,:,0]+aux["T"][:,None]+546.3)/2
    tv=layer*(1+.61*native.dq)
    with np.errstate(over="ignore",invalid="ignore",divide="ignore"):
        values=native.dvalues[:,:,2]*np.exp(-9.80665*1000*b.dz/(287.05*tv))
    b.mask &= np.isfinite(values)&(tv>0)
    b.physical_donors=np.where(b.mask,values,0.)
    b.dv=np.where(b.mask,np.asarray(cube.values[b.d[None,:],b.t[:,None],2]),0.)
    b.n_donors=b.mask.sum(axis=1);b.ready=b.n_donors>=2;b.fit_mask=b.obs&b.ready
    b.case_id=digest({"base":b.case_id,"operator":"hydrostatic_donor_q_layer_predicted_target_T"})
    b.ledger=b.ledger|{"case_id":b.case_id,"support":"donor_TRHp_predicted_target_T","scorable":int(b.fit_mask.sum())}
    return b


def background_features(cases,countries):
    # Country/month background, plus annual and local-mean-solar diurnal height effects.
    intercept=np.column_stack([(cases.country==co)&(cases.month==m) for co in countries for m in range(1,13)])
    z=cases.zt
    return np.column_stack((intercept,z,z*np.sin(cases.phase),z*np.cos(cases.phase),z*np.sin(cases.ht),z*np.cos(cases.ht)))
