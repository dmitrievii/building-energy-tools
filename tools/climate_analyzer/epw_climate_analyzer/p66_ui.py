"""Report-tab Atlas mode; interactive source-specific coverage and exports."""
from __future__ import annotations
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import pandas as pd
import streamlit as st
from .p66_catalogue import prepare_frame,catalogue,LEVELS
from .p66_export import generate_atlas,manifest_csv,PDF_MODES,catalogue_batches
from .p66_memory import container_memory
from .p6_report_structure import CHAPTERS,concise_context

def render_atlas(df,context,reference_df=None):
    st.subheader("Comprehensive Diagram Atlas")
    st.caption("Independent of the curated report basket. Enumerate supported diagrams, their discrete aggregations and statistics. Reference values are fixed for continuous settings; no unlimited parameter sweep.")
    if df is None or df.empty:
        st.info("Load climate data and select a nonempty Data filter.");return
    st.caption(concise_context(context))
    coverage=st.radio("Coverage",LEVELS,index=2,key="p66_coverage")
    try:
        prepared=prepare_frame(df)
        entries=catalogue(prepared,context,coverage)
    except Exception as exc:
        st.error(f"Cannot build atlas catalogue: {exc}");return
    chapters=list(dict.fromkeys(d.chapter for d in entries))
    a,b=st.columns(2)
    key="p66_chapters"
    current=st.session_state.get(key,chapters)
    st.session_state[key]=[c for c in current if c in chapters]
    if a.button("Select all chapters",key="p66_all_chapters"):st.session_state[key]=chapters
    if b.button("Deselect all chapters",key="p66_no_chapters"):st.session_state[key]=[]
    chosen=st.multiselect("Chapters",chapters,key=key,format_func=lambda c:CHAPTERS.get(c,c))
    selected=[d for d in entries if d.chapter in chosen]
    counts=Counter(d.status for d in selected)
    ready=counts["available"]
    a,b,c=st.columns(3)
    a.metric("Catalogue entries",len(selected))
    b.metric("Admitted diagrams",ready)
    c.metric("Unavailable / not registered",len(selected)-ready)
    summary=[]
    for chapter in chosen:
        rows=[d for d in selected if d.chapter==chapter]
        summary.append({"Chapter":CHAPTERS.get(chapter,chapter),"Available":sum(d.status=="available" for d in rows),"Unavailable":sum(d.status!="available" for d in rows)})
    st.dataframe(pd.DataFrame(summary),hide_index=True,use_container_width=True)
    with st.expander("Full visualization catalogue and availability",expanded=False):
        st.dataframe(pd.DataFrame([{"Chapter":CHAPTERS.get(d.chapter,d.chapter),"Diagram":d.title,"Status":d.status,"Reason":d.reason} for d in selected]),hide_index=True,use_container_width=True)
    st.download_button("Download catalogue CSV",data=manifest_csv([asdict(d) for d in selected]),file_name="atlas_catalogue.csv",mime="text/csv",key="p66_catalogue_csv")
    title=st.text_input("Atlas title",value="Comprehensive Diagram Atlas",key="p66_title",max_chars=160)
    mode=st.radio("Output organization",PDF_MODES,index=0,key="p66_output")
    a,b,c=st.columns(3)
    paper=a.radio("Paper",["A4","A3"],index=1,horizontal=True,key="p66_paper")
    orientation=b.radio("Orientation",["Landscape","Portrait"],horizontal=True,key="p66_orientation")
    per_page=c.radio("Diagrams per PDF page",[1,2,4],index=1,horizontal=True,key="p66_panels")
    st.caption("Full 11 pt graph and body typography. Complex diagrams and long interpretations automatically receive a full page or continuation page; the requested panel count is a maximum.")
    batch_size=st.selectbox("Diagrams per export batch",[5,10,20,30,50],index=2,key="p66_batch_size")
    batches=catalogue_batches(selected,batch_size)
    if not batches:return
    numbers=list(range(1,len(batches)+1))
    if st.session_state.get("p66_batch_number") not in numbers:st.session_state["p66_batch_number"]=1
    batch_number=st.selectbox("Export batch",numbers,key="p66_batch_number",
              format_func=lambda n:f"Batch {n} / {len(batches)} · diagrams {(n-1)*batch_size+1}–{min(n*batch_size,ready)}")
    batch=batches[batch_number-1]
    st.caption(f"Full selection: {ready:,} admitted diagrams in {len(batches)} batches. This request generates {len(batch)} diagrams only. Download each batch before generating the next; all catalogue entries remain selectable. The catalogue CSV describes the entire selection; generation outcomes describe this batch only.")
    mem=container_memory()
    if mem:st.caption(f"Container memory: {mem[0]/1024**2:.0f} / {mem[1]/1024**2:.0f} MiB.")
    st.caption("32 MiB output budget per batch. Use smaller batches if memory pressure is reported. Interactive HTML avoids Chromium image rendering.")
    signature=hashlib.sha256(json.dumps([context,coverage,chosen,[d.id for d in batch],batch_number,batch_size,title,mode,paper,orientation,per_page],sort_keys=True,default=str).encode()).hexdigest()
    if st.session_state.get("_p66_atlas_result") and st.session_state["_p66_atlas_result"][0]!=signature:
        st.session_state.pop("_p66_atlas_result",None)
    if st.button("Generate selected batch",key="p66_generate"):
        st.session_state.pop("_p66_atlas_result",None)
        progress=st.progress(0,text="Preparing diagrams")
        try:
            def update(i,n,label):
                progress.progress(min(100,int(100*i/max(n,1))),text=f"{i:,}/{n:,} · {label}")
            data,manifest,metadata=generate_atlas(batch,prepared,context,reference_df=reference_df,title=title,paper=paper,orientation=orientation,
                                  mode=mode,per_page=per_page,progress=update,coverage=coverage)
            metadata["batch_number"]=batch_number
            metadata["batch_count"]=len(batches)
            metadata["batch_size"]=batch_size
            st.session_state["_p66_atlas_result"]=(signature,data,manifest,metadata)
        except Exception as exc:st.error("Atlas generation not completed: "+str(exc))
        finally:progress.empty()
    result=st.session_state.get("_p66_atlas_result")
    if not result or result[0]!=signature:return
    _,data,manifest,metadata=result
    n=Counter(d["status"] for d in manifest)
    if n["failed"]:st.warning(f"{n['generated']:,} diagrams generated; {n['failed']:,} failed. See coverage manifest.")
    elif n["generated"]:st.success(f"{n['generated']:,} diagrams generated; {n['not applicable']:,} have no qualifying observations; {n['unsupported']:,} unsupported/not registered.")
    else:st.warning("No diagrams were generated; see coverage manifest.")
    ext="pdf" if mode=="Single PDF" else "zip"
    if n["generated"]:
        st.download_button("Download atlas",data=data,file_name=f"climate_diagram_atlas_batch_{batch_number:03d}.{ext}",mime="application/pdf" if ext=="pdf" else "application/zip",key="p66_download")
    st.download_button("Download final coverage CSV",data=manifest_csv(manifest),file_name=f"atlas_coverage_batch_{batch_number:03d}.csv",mime="text/csv",key="p66_coverage_csv")
    st.download_button("Download atlas metadata",data=json.dumps(metadata,ensure_ascii=False,indent=2,default=str).encode(),file_name="atlas_metadata.json",mime="application/json",key="p66_meta")
    with st.expander("Generation outcomes",expanded=bool(n["failed"])):
        st.dataframe(pd.DataFrame([{"Diagram":d["title"],"Status":d["status"],"Reason":d["reason"]} for d in manifest]),hide_index=True,use_container_width=True)
    if st.button("Release generated atlas",key="p66_release"):
        st.session_state.pop("_p66_atlas_result",None);st.rerun()
