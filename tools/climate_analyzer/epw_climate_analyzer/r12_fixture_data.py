"""Stable imported numerical fixture for real-session R12 qualification."""
import numpy as np
import pandas as pd
from .byte_cache import bounded_cache

@bounded_cache(name="r12_fixture_private",max_bytes=8*1024**2,max_entries=2,scope="session")
def climate(value):
    return pd.DataFrame({"temperature":np.sin(np.arange(8760)/200)+value,
                         "humidity":np.full(8760,65.)})
