"""Tests for module stability markers."""
from __future__ import annotations
import warnings


def test_experimental_decorator_emits_warning() -> None:
    """@experimental should emit UserWarning on first call."""
    from remora.stability import experimental

    @experimental("topology", since="0.6.0")
    def my_func():
        return 42

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = my_func()
    assert result == 42
    assert len(w) == 1
    assert "topology" in str(w[0].message).lower()
    assert issubclass(w[0].category, UserWarning)


def test_research_only_decorator_emits_warning() -> None:
    from remora.stability import research_only

    @research_only("zkp assurance proofs")
    def proof_func():
        return True

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = proof_func()
    assert result is True
    assert any("research" in str(x.message).lower() for x in w)


def test_stability_constants_exist() -> None:
    from remora.stability import CORE, EXPERIMENTAL, RESEARCH_ONLY
    assert CORE == "core"
    assert EXPERIMENTAL == "experimental"
    assert RESEARCH_ONLY == "research_only"


def test_topology_marked_experimental() -> None:
    import remora.topology as topo
    assert hasattr(topo, "__stability__")
    assert topo.__stability__ == "experimental"


def test_zkp_marked_research_only() -> None:
    import remora.zkp as zkp
    assert hasattr(zkp, "__stability__")
    assert zkp.__stability__ == "research_only"
