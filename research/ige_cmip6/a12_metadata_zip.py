"""Read only named DWD metadata members with bounded authenticated ranges.

No product member may be requested/decompressed. A server ignoring Range is
rejected before reading its body. ZIP64 and ambiguous layouts fail closed.
"""
from __future__ import annotations
from hashlib import sha256
import re
import struct
from urllib.parse import urlsplit
from urllib.request import Request,urlopen
import zlib

IDS={"02928","02932","05750","04997","01443","01224","00757","01346"}


class MetadataArchive:
    def __init__(self,url,opener=urlopen):
        parsed=urlsplit(url)
        match=re.fullmatch(r"/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/historical/stundenwerte_TU_(\d{5})_(\d{8})_(\d{8})_hist.zip",parsed.path)
        if parsed.scheme!="https" or parsed.netloc!="opendata.dwd.de" or parsed.query or parsed.fragment or not match or match[1] not in IDS:
            raise ValueError("A12_ONLY_FROZEN_DWD_METADATA_ARCHIVES")
        if match[2]>"20250110" or match[3]<"20251016":raise ValueError("A12_SOURCE_ARCHIVE_NOT_COVERING_FROZEN_WINDOWS")
        self.url,self.sid,self.opener=url,match[1],opener
        self.total,self.etag=None,None
        self.requests=[];self.entries=[];self.central_sha=None;self.central_start=None

    def _range(self,start,end=None):
        if len(self.requests)>=20:raise ValueError("A12_METADATA_REQUEST_BUDGET")
        value=f"bytes={start}" if start<0 else f"bytes={start}-{end}"
        headers={"Range":value,"Accept-Encoding":"identity","User-Agent":"IGE-A1.2-metadata-only-ranges/1"}
        if self.etag:headers["If-Match"]=self.etag
        with self.opener(Request(self.url,headers=headers),timeout=25) as response:
            if response.geturl()!=self.url:raise ValueError("A12_METADATA_REDIRECT")
            match=re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)",response.headers.get("Content-Range",""))
            if response.status!=206 or not match:raise ValueError("A12_RANGE_REQUIRED_BEFORE_ANY_BODY_READ")
            a,b,total=map(int,match.groups());expected=(total+start,total-1) if start<0 else (start,end)
            if (a,b)!=expected or not 0<=a<=b<total or b-a+1>300000 or total>100000000 or self.total not in (None,total):
                raise ValueError("A12_METADATA_RANGE_SIZE_OR_VERSION")
            etag=response.headers.get("ETag")
            if not etag or etag.startswith('W/'):raise ValueError("A12_STRONG_ETAG_REQUIRED")
            if self.etag is not None and self.etag!=etag:raise ValueError("A12_METADATA_ARCHIVE_ETAG_CHANGED")
            self.total,self.etag=total,etag
            raw=response.read(b-a+2)
            if len(raw)!=b-a+1:raise ValueError("A12_METADATA_RANGE_LENGTH")
            self.requests.append({"range":[a,b],"bytes":len(raw),"sha256":sha256(raw).hexdigest(),
                "ETag":etag,"Last-Modified":response.headers.get("Last-Modified")})
            return raw

    def directory(self):
        if self.entries:return self.entries
        tail=self._range(-22)
        sig,disk,cd_disk,disk_count,count,size,offset,comment=struct.unpack("<4s4H2LH",tail)
        if (sig!=b"PK\x05\x06" or disk or cd_disk or disk_count!=count or comment
                or not 0<count<=100 or not 0<size<=100000 or offset+size!=self.total-22):
            raise ValueError("A12_UNSUPPORTED_OR_AMBIGUOUS_ZIP_END")
        central=self._range(offset,offset+size-1);self.central_start=offset;self.central_sha=sha256(central).hexdigest()
        pos=0
        while pos<len(central):
            if pos+46>len(central):raise ValueError("A12_METADATA_CENTRAL_DIRECTORY_LENGTH")
            h=struct.unpack_from("<4s6H3I5H2I",central,pos);nl,el,cl=h[10:13]
            if h[0]!=b"PK\x01\x02" or pos+46+nl+el+cl>len(central):raise ValueError("A12_METADATA_CENTRAL_DIRECTORY")
            name=central[pos+46:pos+46+nl].decode("utf8" if h[3]&2048 else "cp437")
            self.entries.append({"name":name,"flags":h[3],"method":h[4],"crc32":h[7],
                "compressed":h[8],"uncompressed":h[9],"offset":h[-1]})
            pos+=46+nl+el+cl
        if len(self.entries)!=count or len({e["name"] for e in self.entries})!=count:raise ValueError("A12_DUPLICATE_ZIP_MEMBERS")
        ordered=sorted(self.entries,key=lambda e:e["offset"])
        for a,b in zip(ordered,ordered[1:]):
            if a["offset"]+30+len(a["name"].encode("utf8"))+a["compressed"]>b["offset"]:raise ValueError("A12_OVERLAPPING_ZIP_MEMBERS")
        return self.entries

    def read_metadata(self,name):
        if not re.fullmatch(r"Metadaten_(Parameter|Geographie|Geraete|Stationsname_Betreibername)[A-Za-z0-9_]*_"+self.sid+r"\.txt",name):
            raise ValueError("A12_ONLY_PARAMETER_GEOGRAPHY_DEVICE_NAME_METADATA_ALLOWED")
        self.directory();found=[e for e in self.entries if e["name"]==name]
        if len(found)!=1:raise ValueError("A12_METADATA_MEMBER_NOT_UNIQUE")
        e=found[0]
        if e["flags"]&1 or e["method"] not in (0,8) or not 0<e["compressed"]<=250000 or not 0<e["uncompressed"]<=250000:
            raise ValueError("A12_METADATA_MEMBER_LIMIT")
        start=e["offset"];head=self._range(start,start+29);h=struct.unpack("<4s5H3I2H",head);nl,el=h[-2:]
        if h[0]!=b"PK\x03\x04" or h[2]!=e["flags"] or h[3]!=e["method"] or nl>1000 or el>4096:
            raise ValueError("A12_METADATA_LOCAL_HEADER")
        filename=self._range(start+30,start+29+nl+el)[:nl].decode("utf8" if e["flags"]&2048 else "cp437")
        if filename!=name:raise ValueError("A12_METADATA_LOCAL_NAME_MISMATCH")
        first=start+30+nl+el;last=first+e["compressed"]-1
        next_offset=min([x["offset"] for x in self.entries if x["offset"]>start]+[self.central_start])
        if last>=next_offset:raise ValueError("A12_METADATA_OVERLAPS_OTHER_MEMBER")
        packed=self._range(first,last)
        if e["method"]==8:
            decoder=zlib.decompressobj(-15);raw=decoder.decompress(packed,250001)
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:raise ValueError("A12_METADATA_DEFLATE")
        else:raw=packed
        if len(raw)!=e["uncompressed"] or zlib.crc32(raw)!=e["crc32"]:raise ValueError("A12_METADATA_CRC_LENGTH")
        return raw

    def proof(self):
        return {"url":self.url,"station_id":self.sid,"container_bytes":self.total,"ETag":self.etag,
            "central_directory_sha256":self.central_sha,"members":self.entries,"requests":self.requests,
            "whole_archive_body_read":False,"observation_product_members_requested":False,
            "observation_product_members_decompressed":False}
