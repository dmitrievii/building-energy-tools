"""Read actual NEX time coordinates and bounds, without inventing intervals."""
from __future__ import annotations
import hashlib
import re
import urllib.parse
import urllib.request
import numpy as np


def parse_ascii_array(text,variable,shape):
    # DAP ASCII body: array header, then either a flat row or indexed rows.
    body=text.split("---------------------------------------------",1)
    if len(body)!=2:raise ValueError("P93B3_NOT_DAP_ASCII")
    lines=body[1].strip().splitlines()
    header=variable+"".join("["+str(n)+"]" for n in shape)
    if not lines or lines[0].strip()!=header:raise ValueError("P93B3_DAP_ARRAY_SHAPE_MISMATCH")
    values=[]
    for line in lines[1:]:
        line=re.sub(r"^\s*(?:\[\d+\])+\s*,?\s*","",line)
        if line.strip():values.extend(float(v.strip()) for v in line.split(","))
    a=np.array(values,float)
    if len(a)!=int(np.prod(shape)) or not np.all(np.isfinite(a)):
        raise ValueError("P93B3_DAP_TIME_VALUES_INVALID")
    return a.reshape(shape)


def evaluate_support(metadata,coordinates,dds=None,bounds=None):
    variable=metadata["variable"];year=metadata.get("year",2013)
    attrs=metadata.get("blocks",{}).get("time",{})
    a=np.asarray(coordinates,float)
    units=attrs.get("units","")
    if attrs.get("calendar") not in ("365_day","noleap") or not re.fullmatch(
            r"days since 1850-01-01 (?:0:0:0(?:\.0)?|00:00:00)",units):
        raise ValueError("P93B3_UNSUPPORTED_NATIVE_TIME_ORIGIN")
    if a.shape!=(365,) or not np.all(np.isfinite(a)) or not np.allclose(np.diff(a),1.,atol=1e-10,rtol=0):
        raise ValueError("P93B3_TIME_AXIS_NOT_365_CONSECUTIVE_DAYS")
    expected=(year-1850)*365+np.arange(365)+.5
    if not np.allclose(a,expected,atol=1e-10,rtol=0):
        raise ValueError("P93B3_TIME_AXIS_NOT_EXPECTED_NOLEAP_YEAR_NOON")
    declared=attrs.get("bounds")
    present=bool(declared and dds is not None and re.search(r"\b(?:Float64|Float32)\s+"+re.escape(declared)+r"\s*\[",dds))
    report={"variable":variable,"year":year,"calendar":attrs["calendar"],"units":units,
        "n_time_coordinates":365,"coordinate_first":float(a[0]),"coordinate_last":float(a[-1]),
        "coordinate_role":"DAILY_NOON_LABEL_NOT_PROOF_OF_AVERAGING_WINDOW",
        "coordinates_sha256":hashlib.sha256(a.astype("<f8").tobytes()).hexdigest(),
        "bounds_attribute":declared,"bounds_variable_in_dds":present if dds is not None else None,
        "status":"COORDINATES_READ_INTERVAL_BOUNDS_UNRESOLVED","interval_semantics_verified":False}
    if declared and dds is not None and not present:
        report["bounds_status"]="DANGLING_ATTRIBUTE_VARIABLE_ABSENT_IN_DDS"
    elif not declared:report["bounds_status"]="NO_VARIABLE_SPECIFIC_BOUNDS_ATTRIBUTE"
    else:report["bounds_status"]="DECLARED_BOUNDS_VALUES_NOT_READ"
    if bounds is not None:
        b=np.asarray(bounds,float)
        if (not present or b.shape!=(365,2) or not np.all(np.isfinite(b)) or
                not np.allclose(b[:,1]-b[:,0],1.,atol=1e-10,rtol=0) or
                not np.allclose(b.mean(axis=1),a,atol=1e-10,rtol=0)):
            raise ValueError("P93B3_INVALID_NATIVE_TIME_BOUNDS")
        report.update(status="NATIVE_UTC_DAY_BOUNDS_READ",bounds_status="VALUES_READ_AND_VALIDATED",
            interval_semantics_verified=True,bounds_first=b[0].tolist(),bounds_last=b[-1].tolist(),
            bounds_sha256=hashlib.sha256(b.astype("<f8").tobytes()).hexdigest())
    return report


def fetch_time_support(metadata,fetch=None):
    if metadata["status"]!="SOURCE_METADATA_READ":
        return {"variable":metadata["variable"],"year":metadata.get("year",2013),
            "status":"TIME_SOURCE_BLOCKED_METADATA_UNAVAILABLE","interval_semantics_verified":False}
    base=metadata["url"].removesuffix(".das");responses=[];errors=[]
    def read(suffix):
        url=base+suffix
        for _ in range(2):
            try:
                if fetch is None:
                    with urllib.request.urlopen(url,timeout=20) as f:raw=f.read(200001)
                else:raw=fetch(url)
                if len(raw)>200000:raise ValueError("P93B3_TIME_RESPONSE_TOO_LARGE")
                responses.append({"url":url,"sha256":hashlib.sha256(raw).hexdigest()})
                return raw.decode()
            except (OSError,ValueError,UnicodeError) as e:errors.append(str(e))
        return None
    try:
        text=read(".ascii?"+urllib.parse.quote("time[0:1:364]",safe=""))
        if text is None:raise ValueError("P93B3_TIME_COORDINATES_NOT_READ")
        a=parse_ascii_array(text,"time",(365,))
        dds=read(".dds")
        declared=metadata["blocks"]["time"].get("bounds");bounds=None
        if declared and re.fullmatch(r"[A-Za-z_]\w*",declared) and dds and re.search(
                r"\b(?:Float64|Float32)\s+"+re.escape(declared)+r"\s*\[",dds):
            text=read(".ascii?"+urllib.parse.quote(declared+"[0:1:364][0:1:1]",safe=""))
            if text:bounds=parse_ascii_array(text,declared,(365,2))
        report=evaluate_support(metadata,a,dds,bounds)
    except ValueError as e:
        report={"variable":metadata["variable"],"year":metadata.get("year",2013),
            "status":"TIME_SOURCE_BLOCKED_OR_UNQUALIFIED","interval_semantics_verified":False,"reason":str(e)}
    return {**report,"source_responses":responses,"source_errors":errors}
