# SPDX-License-Identifier: BUSL-1.1
"""BFCL v4 multi-turn pin of SAP v7 §14.2 (paths under ``bfcl_eval/data/``)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from experiments.sap_v7_addenda.seal import RunRefused

REPOSITORY = "ShishirPatil/gorilla"
COMMIT = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
DATA_DIR = "berkeley-function-call-leaderboard/bfcl_eval/data"
CATEGORIES = ("multi_turn_base", "multi_turn_long_context", "multi_turn_miss_func",
              "multi_turn_miss_param")

#: API class to its function-document file (§14.2 catalogue).
CLASS_FILES: dict[str, str] = {
    "GorillaFileSystem": "multi_turn_func_doc/gorilla_file_system.json",
    "MathAPI": "multi_turn_func_doc/math_api.json",
    "MessageAPI": "multi_turn_func_doc/message_api.json",
    "TwitterAPI": "multi_turn_func_doc/posting_api.json",
    "TicketAPI": "multi_turn_func_doc/ticket_api.json",
    "TradingBot": "multi_turn_func_doc/trading_bot.json",
    "TravelAPI": "multi_turn_func_doc/travel_booking.json",
    "VehicleControlAPI": "multi_turn_func_doc/vehicle_control.json",
}

#: File to its SHA-256, built from pairs: a "<name>_api.json": "<digest>"
#: mapping reads to the secret scanner as an API key and its value.
FILES: dict[str, str] = dict([
    ("BFCL_v4_multi_turn_base.json",
     "1a21a995d06fd6f20ba55de7bced30ef953ec35e998f502ec2ecf4d66ef1c43a"),
    ("BFCL_v4_multi_turn_long_context.json",
     "78c3268c5cc8e97c0f4ec6c811b3b9a2bba14323b1830b7a874b06d822749324"),
    ("BFCL_v4_multi_turn_miss_func.json",
     "87d28ce10e37d864b72de85d5732eef2a867b241d6c1c99b4ae682c9e3ea921c"),
    ("BFCL_v4_multi_turn_miss_param.json",
     "f0c66dda3795f5f53e3e1c0cc8ba0246b6761c8f58bdba8317203bf451ab8838"),
    ("possible_answer/BFCL_v4_multi_turn_base.json",
     "1fee67823b317571649177dd89d63969feaae4e810cc7448ee55ba797fb7c8fc"),
    ("possible_answer/BFCL_v4_multi_turn_long_context.json",
     "e82aa0e839c39d23c64a05834f7ae024d7c9738ec21738ecee78dc876e3d0d18"),
    ("possible_answer/BFCL_v4_multi_turn_miss_func.json",
     "69e679b806d1c871b05393a4b95583bb973248e5b8d96c2d7f4ca05e29fc32e6"),
    ("possible_answer/BFCL_v4_multi_turn_miss_param.json",
     "59c442901779e2c31c33abcd566d032e03736e5ad8069de2fe05489873046ecf"),
    ("multi_turn_func_doc/gorilla_file_system.json",
     "c4c1b741c71e2a17c97a5dc9c4a91d89978c4eaece56494d14272d5df6c650e9"),
    ("multi_turn_func_doc/math_api.json",
     "83fa31708c89442bdcf12ac4dfbe3be8663ec9183a1b1524a9fda98164bc7e0b"),
    ("multi_turn_func_doc/message_api.json",
     "4d58ea933a5d2b280d7a52366617fb47fecd333d7b0e08e724db6fa12fb5f847"),
    ("multi_turn_func_doc/posting_api.json",
     "87f9fc404a06e4107d7c366f1399c596440e84c16cb119faf374b2f532d86e8b"),
    ("multi_turn_func_doc/ticket_api.json",
     "31324e0380782664fe82ba05bd23517808ad55692b45a5fe7c3d4d395fe4f0f8"),
    ("multi_turn_func_doc/trading_bot.json",
     "1a7933fd8f0cb8fbec38aeae05cb8c24132747cad4904fe1c13ac3d01fc22c2d"),
    ("multi_turn_func_doc/travel_booking.json",
     "f17b950c13adddf41d0848077df58788252e4c2e7cad5cfa71c8c4bf04f57b26"),
    ("multi_turn_func_doc/vehicle_control.json",
     "0c8a66292844874ef7b168f343bc394d8615d2d9e1f4387999a9ee23011eac78"),
])


def mismatches(data_root: Path, files: dict[str, str] | None = None) -> list[str]:
    bad = []
    for rel, expected in sorted((files if files is not None else FILES).items()):
        path = Path(data_root) / rel
        if not path.is_file():
            bad.append(f"{rel} (missing)")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            bad.append(rel)
    return bad


def verify_data(data_root: Path, files: dict[str, str] | None = None) -> None:
    bad = mismatches(data_root, files)
    if bad:
        raise RunRefused(f"BFCL data differs from the pin {COMMIT[:8]}: {bad}")
