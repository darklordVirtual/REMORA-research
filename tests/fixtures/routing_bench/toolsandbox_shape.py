# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Synthetic stand-in for a ToolSandbox scenario module.

ToolSandbox is licensed under Apple's own terms, not an OSI license, so neither
its source nor anything derived from it may be committed here. This file is
original REMORA content that reproduces the *shape* the adapter parses —
``ScenarioExtension(...)`` calls with ``messages``, ``tool_allow_list``,
``tool_deny_list``, ``milestones`` and ``minefields`` — using invented scenario
names, prompts and tool names.

It exercises the parser without redistributing upstream content. An integration
test runs the same adapter against the real cached module when it is present
locally, and skips otherwise.

This module is never imported; it is only parsed as text.
"""

from tool_sandbox.common.evaluation import Milestone, Minefield, SnapshotConstraint
from tool_sandbox.common.execution_context import RoleType
from tool_sandbox.common.scenario import ScenarioExtension


def get_extensions(base_scenarios):
    return [
        # Unanswerable: milestones empty, the only allow-listed tool is mined.
        ScenarioExtension(
            name="find_current_altitude_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": "You want your altitude. You have no other information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What altitude am I at?",
                },
            ],
            tool_allow_list=["search_altitude_by_coordinates"],
            tool_deny_list=["get_current_position", "read_barometer"],
            milestones=[],
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            target_dataframe={
                                "sender": RoleType.AGENT,
                                "content": "search_altitude_by_coordinates",
                            }
                        )
                    ]
                )
            ],
        ),
        # Second unanswerable case with two allow-listed tools, one mined.
        ScenarioExtension(
            name="find_neighbour_name_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What is my neighbour called?",
                },
            ],
            tool_allow_list=["search_contact_by_name", "search_directory"],
            tool_deny_list=["get_current_position"],
            milestones=[],
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            target_dataframe={"content": "search_directory"}
                        )
                    ]
                )
            ],
        ),
        # Answerable in part: milestones non-empty, so tool_required is True and
        # the mined call is merely wrong rather than the task being impossible.
        ScenarioExtension(
            name="send_reminder_partial_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Remind me about the meeting.",
                },
            ],
            tool_allow_list=["create_reminder", "send_message"],
            tool_deny_list=[],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            target_dataframe={"content": "create_reminder"}
                        )
                    ]
                )
            ],
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            target_dataframe={"content": "send_message"}
                        )
                    ]
                )
            ],
        ),
    ]
