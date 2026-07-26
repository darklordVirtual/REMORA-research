from dataclasses import dataclass, field
@dataclass
class EffectBlock:
    executed: bool = False
    tool_call_hash: str | None = None
    effect_outcome: str | None = None
    ledger_entry: dict = field(default_factory=dict)
