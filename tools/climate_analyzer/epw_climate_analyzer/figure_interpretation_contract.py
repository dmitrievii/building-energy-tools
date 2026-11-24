"""One figure -> one frozen scientific interpretation, reused by every output.

No climate calculations or Plotly serialization are performed in this module.
The binding is a compact digest in the existing figure layout metadata.
The actual interpretation stays once in the report snapshot and must be
replayed verbatim in the website, HTML, PDF and atlas outputs.
"""
from __future__ import annotations

import hashlib

BINDING_KEY="ige_interpretation_sha256"
VERSION_KEY="ige_interpretation_schema"
VERSION="R2-unified-1"


def _digest(interpretation):
    return hashlib.sha256(str(interpretation).encode("utf-8")).hexdigest()


def bind_figure_interpretation(fig, interpretation):
    """Bind one authoritative narrative to a figure in O(text) work.

    Existing physics metadata and trace geometry are preserved. Different
    text for an already bound figure is a contract violation, not a reason
    to silently overwrite previously displayed science.
    """
    if not hasattr(fig,"layout"):
        raise TypeError("A Plotly figure is required for interpretation binding.")
    meta=getattr(fig.layout,"meta",None)
    if meta is None:meta={}
    if not isinstance(meta,dict):
        raise ValueError("Figure metadata must be a dictionary for interpretation binding.")
    digest=_digest(interpretation)
    previous=meta.get(BINDING_KEY)
    if previous is not None and previous!=digest:
        raise ValueError("Figure interpretation changed after it was bound.")
    if previous==digest:return fig
    updated=dict(meta)
    updated[BINDING_KEY]=digest
    updated[VERSION_KEY]=VERSION
    fig.update_layout(meta=updated)
    return fig


def validate_figure_interpretation(fig, interpretation, *, require_binding=False):
    """Validate source-bound text before report preview/export.

    Legacy saved figures without a binding are admitted unchanged; newly
    bound figures fail closed on mismatch.
    """
    meta=getattr(getattr(fig,"layout",None),"meta",None)
    current=meta.get(BINDING_KEY) if isinstance(meta,dict) else None
    if current is None:
        if require_binding:raise ValueError("Missing figure interpretation binding.")
        return False
    if current!=_digest(interpretation):
        raise ValueError("Exported interpretation differs from the figure's original interpretation.")
    return True
