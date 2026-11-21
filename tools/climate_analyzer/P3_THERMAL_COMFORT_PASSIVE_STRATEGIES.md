# P3 — Thermal Comfort and Passive Strategies

Implementation candidate. OTC-01–05 UTCI (heat map, stress duration, duration curve, paired direct shade, sensitivity). HVAC-05 sensible and latent ventilation load; HVAC-06 adaptive temperature bands. NV-01–04 observed joint suitability and uninterrupted daily/nightly runs. H-04 condensation potential at specified surface temperature; H-05 moisture conditioning mass; SD-04 measured/source illuminance availability. PET remains P6.

UTCI Bröde et al. (2012), DOI 10.1007/s00484-011-0454-1; pythermalcomfort 4.8.1 with strict applicability checks, 10 m wind assumption/factor. MRT scenario uses spherical-equivalent radiation: fourth power of absolute radiant temperature = [0.5(Lsky+sigma*Tground^4)+(alpha/epsilon)(0.5(DHI+rho*GHI)+fproj*DNI)]/sigma. Divide interval Wh/m² by duration before computing flux. Direct shade removes beam alone. Longwave is required; no fabricated sky flux. Ground blackbody at specified offset to Ta. Not a measured human MRT or urban prediction.

Adaptive screening EN 16798-1:2019, neutral=.33Trm+18.8, I (+2,-3), II (+3,-4), III (+4,-5); 10–30 °C only; seven complete prior days normalized alpha=.8 (finite-history approximation). Source: https://doi.org/10.1016/j.buildenv.2020.107313 . No indoor compliance. Load proxy uses dry-air actual mass flow from specific volume, variable sensible cp, reference latent heat 2501 kJ/kg, native interval duration. Moisture is water mass. No recovery or HVAC system efficiency.

References: https://pythermalcomfort.readthedocs.io/en/latest/documentation/models.html ; https://confluence.ecmwf.int/spaces/CKB/pages/650383669/UTCI+Timeseries+User+Guide .
Qualification: numerical reference fixture, model limits, radiation closure, interval-energy and moisture units, causal complete days, gaps and duration closure. Independent official Fortran comparison, site MRT validation, cloud dependency installation and live browser/source/export qualification remain pending.
