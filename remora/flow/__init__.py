# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Derived information-flow control (docs/design/derived-information-flow-control-v1.md).

IFC-01 provides the label lattice. With ``REMORA_FLOW_CONTROL=1`` the
execution API's decision reads the flow verdict (IFC-05b, ``observe.py``);
with it off nothing here changes a decision.
"""
from remora.flow.label import (
    BOTTOM,
    PUBLIC,
    Integrity,
    Label,
    LabelRefused,
    canonical_bytes,
    field_value_label,
    flows_to,
    join,
    join_all,
    leq,
)

__all__ = [
    "BOTTOM",
    "PUBLIC",
    "Integrity",
    "Label",
    "LabelRefused",
    "canonical_bytes",
    "field_value_label",
    "flows_to",
    "join",
    "join_all",
    "leq",
]
