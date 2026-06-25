# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for role-differentiated oracle wrappers."""
from __future__ import annotations


from remora.oracles.mock import MockOracle
from remora.oracles.roles import OracleRole, RoleOracle, make_role_swarm
from remora.engine import Remora
from remora.genome import Genome


class TestRoleOracle:

    def _base(self) -> MockOracle:
        return MockOracle(name="base", bias=True, noise=0.0)

    def test_name_includes_role(self):
        oracle = RoleOracle(self._base(), OracleRole.SOURCE)
        assert "base" in oracle.name
        assert "source" in oracle.name

    def test_role_prompt_injected(self):
        """The role instruction prefix should appear in the prompt sent to the base oracle."""
        received: list[str] = []

        class CapturingOracle(MockOracle):
            def _call(self, prompt: str):
                received.append(prompt)
                return super()._call(prompt)

        base = CapturingOracle("capture", bias=True, noise=0.0)
        oracle = RoleOracle(base, OracleRole.SKEPTIC)
        oracle.ask("Is the sky blue?")

        assert received, "No prompt was received"
        assert "SKEPTIC" in received[0].upper() or "skeptic" in received[0].lower()

    def test_all_roles_produce_response(self):
        for role in OracleRole:
            oracle = RoleOracle(self._base(), role)
            response = oracle.ask("Test question?")
            assert response is not None
            assert response.provider == oracle.name

    def test_anti_convergence_context_injected(self):
        received: list[str] = []

        class CapturingOracle(MockOracle):
            def _call(self, prompt: str):
                received.append(prompt)
                return super()._call(prompt)

        base = CapturingOracle("cap", bias=True, noise=0.0)
        ctx = "Previous oracle said: YES with support=0.8"
        oracle = RoleOracle(base, OracleRole.ADVERSARIAL, anti_convergence_context=ctx)
        oracle.ask("Test?")
        assert ctx in received[0]
        assert "DIFFERENT angle" in received[0] or "non-overlapping" in received[0]

    def test_implements_oracle_abc(self):
        from remora.core import Oracle
        oracle = RoleOracle(self._base(), OracleRole.JUDGE)
        assert isinstance(oracle, Oracle)


class TestMakeRoleSwarm:

    def test_default_swarm_three_oracles(self):
        bases = [MockOracle(f"m{i}") for i in range(3)]
        swarm = make_role_swarm(bases)
        assert len(swarm) == len(list(OracleRole))  # 6 roles
        roles = [o.role for o in swarm]
        assert OracleRole.SOURCE in roles
        assert OracleRole.SKEPTIC in roles
        assert OracleRole.DOMAIN in roles

    def test_swarm_cycles_oracles(self):
        bases = [MockOracle(f"m{i}") for i in range(2)]
        swarm = make_role_swarm(bases, roles=[OracleRole.SOURCE, OracleRole.SKEPTIC, OracleRole.DOMAIN])
        assert len(swarm) == 3
        assert swarm[2]._base.name == "m0"  # cycled back

    def test_swarm_with_custom_roles(self):
        bases = [MockOracle("m0"), MockOracle("m1")]
        roles = [OracleRole.SOURCE, OracleRole.ADVERSARIAL]
        swarm = make_role_swarm(bases, roles=roles)
        assert swarm[0].role == OracleRole.SOURCE
        assert swarm[1].role == OracleRole.ADVERSARIAL

    def test_role_swarm_works_in_remora(self):
        """Role-swarm oracles must be compatible with the Remora engine."""
        bases = [MockOracle(f"m{i}", bias=True, noise=0.0) for i in range(3)]
        swarm = make_role_swarm(
            bases,
            roles=[OracleRole.SOURCE, OracleRole.SKEPTIC, OracleRole.VERIFIER],
        )
        genome = Genome(max_iterations=2, max_subquestions=1, negation_ratio=0.0)
        engine = Remora(oracles=swarm, genome=genome)
        state = engine.run("Is the sky blue?")
        report = engine.report(state)
        assert report["oracle_calls"] > 0
        assert report["open_candidates"] >= 1


class TestAntiConvergence:

    def test_anti_convergence_flag_in_genome(self):
        g = Genome(enable_anti_convergence=True, anti_convergence_max_context_claims=2)
        assert g.enable_anti_convergence is True
        assert g.anti_convergence_max_context_claims == 2

    def test_anti_convergence_disabled_by_default(self):
        g = Genome()
        assert g.enable_anti_convergence is False

    def test_anti_convergence_runs_in_engine(self):
        """Engine with anti_convergence=True must complete without error."""
        oracles = [MockOracle(f"m{i}", bias=True, noise=0.0) for i in range(3)]
        genome = Genome(
            max_iterations=3,
            max_subquestions=1,
            negation_ratio=0.0,
            enable_anti_convergence=True,
            anti_convergence_max_context_claims=2,
        )
        engine = Remora(oracles=oracles, genome=genome)
        state = engine.run("Does CRISPR enable gene editing?")
        report = engine.report(state)
        assert report["iterations"] > 0
