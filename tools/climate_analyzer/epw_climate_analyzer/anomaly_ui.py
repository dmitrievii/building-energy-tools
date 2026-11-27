"""Historical anomaly controls; target filter and reference archive are distinct."""
from __future__ import annotations
from .climate_anomalies import available, QUANTITIES, VIEWS, figure, MIN_REFERENCE_YEARS

def panel(st,target,reference,render):
    st.header("Climate anomalies")
    options=available(reference)
    if not options:
        st.info("Load a real multi-year historical observation archive from Climate source to establish a reference climatology.")
        return
    years=sorted(set(reference.index.year))
    if len(years)<MIN_REFERENCE_YEARS:
        st.info("Load at least three historical years for a short-period reference; a 30-year reference is preferable.")
        return
    st.caption("The global Data filter selects target observations. The reference interval uses the full loaded archive at the same station, quality policy, source resolution and analysis clock.")
    c=st.selectbox("Climate quantity",options,format_func=lambda k:QUANTITIES[k].label,key="r221_anomaly_quantity")
    default=(1991,2020) if years[0]<=1991 and years[-1]>=2020 else (years[0],years[-1])
    start,end=st.slider("Historical reference years",min_value=int(years[0]),max_value=int(years[-1]),value=default,key="r221_anomaly_reference")
    if end-start+1<MIN_REFERENCE_YEARS:
        st.info("Select at least three reference years.")
        return
    view=st.selectbox("Chart type",VIEWS,key="r221_anomaly_view")
    targets=sorted(set(target.index.year))
    if not targets:
        st.info("No target years remain in the Data filter.")
        return
    year=st.selectbox("Target year",targets,index=len(targets)-1,key="r221_anomaly_year") if view in VIEWS[:2] else None
    relative=False
    if QUANTITIES[c].total and view!=VIEWS[1]:
        relative=st.radio("Anomaly representation",["Absolute difference","Relative difference [%]"],horizontal=True,key="r221_anomaly_relative").startswith("Relative")
    try:
        f,note,a=figure(target,reference,c,start,end,view,year=year,relative=relative)
    except ValueError as exc:
        st.info(str(exc));return
    render(f,note)
    with st.expander("Reference climatology and coverage",expanded=False):
        st.caption("Reference sample counts count valid year-month aggregates. Hourly months require complete coverage; provider-native monthly records retain their published semantics. Annual values require all twelve months.")
        st.dataframe(a["reference"],use_container_width=True)
        st.caption(f"Complete reference years for annual statistics: {a['annual_n']}")
        st.dataframe(a["coverage"],use_container_width=True)
        st.download_button("Download monthly anomalies CSV",a["anomalies"].to_csv().encode("utf-8"),file_name="monthly_anomalies.csv",mime="text/csv",key="r221_anomaly_csv")
