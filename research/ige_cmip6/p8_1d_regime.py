#!/usr/bin/env python3
"""IGE P8.1D: terrain regime and inversion-susceptibility research model.

This is a *climatological cold-air pooling proxy*, NOT a detection of an
observed thermal inversion.  A true inversion requires temperature profiles or
simultaneous stations at different heights with traceable sampling conditions.
Only static DEM features and 1991-2010 donor observations are used to fit it.
"""
from __future__ import annotations
import math
import numpy as np

NAMES=('valley_cold','ridge_cold','valley_warm','ridge_warm')

def regime(site):
    """Fixed, physically interpretable DEM rules, not learned labels."""
    t=float(site['tpi_1500_m']);large=float(site['tpi_5000_m'])
    rough=float(site['rugged_1500_m']);slope=float(site.get('slope_250m_proxy',0.))
    z=float(site['hoehe_m'])
    if z>=1500 and t>=100 and large>=100:return 'alpine_crest'
    if t>=100 and large>=100:return 'ridge'
    if t<=-50 and large<=-120 and rough>=60:return 'enclosed_valley'
    if rough<40 and slope<.10:return 'open_lowland'
    return 'slope_transition'

def susceptibility(site):
    """Continuous non-negative morphology indices with bounded leverage.

    Cold-air pooling in complex terrain is more likely for concave lower
    positions, but terrain alone cannot prove that an inversion occurred.
    """
    t=float(site['tpi_1500_m']);t5=float(site['tpi_5000_m'])
    rug=float(site['rugged_1500_m']); slope=float(site.get('slope_250m_proxy',0.))
    if not all(map(math.isfinite,(t,t5,rug,slope))) or rug<0 or slope<0:
        raise ValueError('Nonfinite / impossible DEM morphology')
    enclosure=np.clip((rug-25.)/150.,0.,1.)
    valley=(max(0.,-t)/200.)*enclosure
    valley*=.5+.5*min(1.,max(0.,-t5)/400.)
    ridge=max(0.,t)/200.*(.5+.5*min(1.,max(0.,t5)/500.))
    return min(3.,valley), min(3.,ridge)

def season_factors(month):
    if not isinstance(month,int) or not 1<=month<=12:raise ValueError('Invalid calendar month')
    cold=max(0.,math.cos(2*math.pi*(month-1)/12.))
    return cold, 1.-cold

def features(site,month):
    v,r=susceptibility(site);c,w=season_factors(month)
    return np.array([v*c,r*c,v*w,r*w],float)

def fit_donor_only(donors,month, ridge_penalty=35.):
    """Fit DEM features to REGIONAL-trend residuals on donor TRAIN normals.

    No target station and no 2011-2020 target observations permitted; caller
    supplies donors explicitly. Fitted slopes regularized/shrunk and capped.
    Ridge regression on partialled features reduces geographic confounding.
    """
    if len(donors)<20:raise ValueError('At least 20 donor calibration stations required')
    s=sorted(donors,key=lambda x:x['station_id'])
    zz=np.asarray([float(x['hoehe_m']) for x in s],float)
    lat=np.asarray([float(x['lat']) for x in s],float)
    lon=np.asarray([float(x['lon']) for x in s],float)
    y=np.asarray([float(x['tmittel'][month-1]) for x in s],float)
    X=np.column_stack([np.ones(len(s)),(lat-lat.mean()),(lon-lon.mean()),(zz-zz.mean())/1000.])
    Z=np.vstack([features(x,month) for x in s])
    if not (np.isfinite(X).all() and np.isfinite(y).all() and np.isfinite(Z).all()):
        raise ValueError('Invalid donor-only temperature/geometry')
    Xpinv=np.linalg.pinv(X,rcond=1e-10)
    ry=y-X@Xpinv@y
    rz=Z-X@Xpinv@Z
    # fixed regularizer means rare mountainous regimes cannot acquire large
    # unstable coefficients from only a few stations.
    co=np.linalg.solve(rz.T@rz+ridge_penalty*np.eye(4),rz.T@ry)
    return np.clip(co,-1.0,1.0)

def predict_regime(base, target,donors,weights,coeff,month, winter_only=False):
    """Correct regional IDW by target-vs-donor terrain contrast.

    Identical terrain features imply exactly zero correction, by construction.
    Bounds ±1°C prevent unconstrained mountain extrapolation.
    """
    if any(x['station_id']==target['station_id'] for x in donors):
        raise AssertionError('TARGET LEAKAGE')
    w=np.asarray(weights,float)
    if len(donors)!=len(w) or len(donors)<1 or not np.isfinite(w).all() or abs(w.sum()-1)>1e-8:
        raise ValueError('Invalid donor weights')
    contrast=features(target,month)-w@np.vstack([features(x,month) for x in donors])
    co=np.asarray(coeff,float).copy()
    if co.shape!=(4,):raise ValueError('Bad correction coefficients')
    if winter_only:co[2:]=0
    correction=float(np.clip(co@contrast,-1.,1.))
    return float(base+correction),correction


def metadata_validation(source):
    s=set()
    for x in source:
        sid=int(x['station_id'])
        if sid in s:raise ValueError('Duplicate station id')
        s.add(sid)
        if x['station_height_m']< -500 or x['station_height_m']>5000:raise ValueError('Unphysical station elevation')
    return len(s)