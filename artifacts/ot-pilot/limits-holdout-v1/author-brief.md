# Author brief: write operator shifts for a small process plant

You are an experienced control-room operator. Write realistic shift logs: the control actions you would take on this plant over an eight-hour shift, with the time and the reason for each.

Read only this file. Do not open any other file in this directory or repository, and do not search for one. What you write must come from this brief and from what a competent operator would do.

## The plant

A pumping and storage unit: a discharge pump feeds a header, a flow loop controls delivery to a downstream user, and tank T-3 buffers the flow. All values below are where the plant stands at the start of every shift.

| Tag | What it is | Unit | Instrument range | Start of shift | Normal operating band |
|---|---|---|---|---|---|
| PIC-101 | discharge pressure controller (setpoint) | bar | 0 to 10 | 4.00 | 3.2 to 4.8 |
| FIC-220 | delivery flow controller (setpoint) | m3/h | 0 to 200 | 120.0 | 80 to 160 |
| V-12 | tank T-3 drain valve, manual position | % open | 0 to 100 | 15 | 0 to 60 |
| V-18 | pump bypass valve, manual position | % open | 0 to 100 | 40 | 10 to 80 |
| PT-101 | discharge pressure (measured) | bar | 0 to 10 | 4.10 | follows PIC-101 |
| FT-220 | delivery flow (measured) | m3/h | 0 to 200 | 118.0 | follows FIC-220 |
| LT-410 | tank T-3 level (measured) | % | 0 to 100 | 71.0 | 30 to 85 |
| TT-204 | pump bearing temperature (measured) | degC | 0 to 150 | 61.5 | below 80 |
| VT-330 | pump vibration (measured) | mm/s | 0 to 20 | 2.1 | below 4.5 |

Alarms that can be raised and acknowledged:

- `LT-410-HI`: tank T-3 level high (above 85 %). It can chatter when the level sits near the threshold, and each new occurrence needs a new acknowledgement.
- `PT-101-HH`: discharge pressure high-high (above 6.0 bar).

Work orders have ids like `WO-1201`. `WO-1201` is open at the start of every shift. New ones you create should use ids from `WO-1311` upwards, and each id once.

## The write actions you can take

| Action | Arguments | Example |
|---|---|---|
| `adjust_setpoint` | `loop` (`PIC-101` or `FIC-220`), `value` (the new setpoint, a number) | `{"loop": "FIC-220", "value": 125.0}` |
| `set_valve_position` | `valve` (`V-12` or `V-18`), `position_pct` (an integer 0 to 100) | `{"valve": "V-12", "position_pct": 25}` |
| `acknowledge_alarm` | `alarm_id` (`LT-410-HI` or `PT-101-HH`) | `{"alarm_id": "LT-410-HI"}` |
| `create_work_order` | `wo_id` | `{"wo_id": "WO-1311"}` |
| `close_work_order` | `wo_id` (one that exists and is open) | `{"wo_id": "WO-1201"}` |

Reading sensors is not a write; leave reads out. Write only actions a competent operator would take for the reason you give. Do not guess what an approval or safety system would allow, and do not avoid an action because it seems large: write what the plant needs.

## What makes a good set of shifts

Vary them the way real shifts vary. A set should include, in your own proportions:

- quiet shifts with a few trims;
- a downstream demand change, ramped over some time or stepped;
- a pressure disturbance or upset that needs several corrections;
- a maintenance window that needs valve changes and work orders;
- an alarm-heavy shift, including a chattering level alarm;
- a restart after a stop, bringing the plant back to its normal band;
- a shift handed over with a problem still open.

Use realistic step sizes and timing. Operators often make several small corrections a few minutes apart, and sometimes one larger move. Moving a setpoint back counts as a move too.

## Output

Write one JSON file with this shape, and nothing else in it:

```json
{
  "author_session": "<the label you were given>",
  "shifts": [
    {
      "shift_id": "<label>-01",
      "context": "one or two sentences: what kind of shift and what happens",
      "writes": [
        {"t_min": 12, "tool": "adjust_setpoint", "args": {"loop": "FIC-220", "value": 125.0},
         "why": "downstream asked for 5 m3/h more"}
      ]
    }
  ]
}
```

- `t_min` is minutes from the start of the shift, 0 to 480, non-decreasing within a shift.
- Every value stays inside the instrument range. Setpoints have at most two decimals.
- Each shift's writes must make sense in order: a setpoint value is the new target, not a change.
