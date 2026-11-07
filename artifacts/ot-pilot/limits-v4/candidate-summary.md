# The control system's limits, in plain words

These are the cumulative limits that decide each write in your episodes. Nothing else about the control system is given to you, and you must not guess further rules.

Every window is a sliding window: a limit counts what was charged in the last 60 minutes, or the last 24 hours, at the moment of the write. A write is refused when its charge would take a counter past its maximum. A refused write is charged nothing.

| Limit | Maximum |
|---|---|
| PIC-101 setpoint movement | 1.60 bar per 60 minutes |
| FIC-220 setpoint movement | 180 m3/h per 60 minutes |
| Valve travel, each valve separately | 200 percentage points per 60 minutes |
| Acknowledgements, each alarm separately | 6 per 60 minutes |
| Work orders created | 20 per 24 hours |
| Work orders closed | 20 per 24 hours |

How movement is charged:

- The charge of a setpoint or valve write is the distance from the value the plant reports just before the write to the new value.
- **FIC-220 at 0 is the safe state.** A write that sets FIC-220 to exactly 0 is never refused and is charged nothing.
- **Towards the safe state is free.** A FIC-220 write whose new value lies between the current value and 0 is charged nothing and is not refused by a full counter. Moving away from 0 is charged.
- **PIC-101 while delivery is stopped.** While the plant reports FIC-220 at exactly 0, PIC-101 writes are charged nothing. Once FIC-220 leaves 0, they are charged again.
- Acknowledgements and work orders are charged 1 each.
