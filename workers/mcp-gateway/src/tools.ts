/**
 * The MCP tool surface.
 *
 * These schemas describe the *shape* of a call, nothing more. Risk tier,
 * action type, domain and every other safety signal are derived server-side
 * from the signed tool registry inside REMORA; a caller cannot assert its way
 * to an ACCEPT (see servers/execution_contracts.py, ToolCallRequest). Adding a
 * field here can never widen authority — it only changes what the agent is
 * able to propose.
 */
export interface GovernedTool {
  name: string;
  description: string;
  inputSchema: {
    type: "object";
    properties: Record<string, { type: string; description: string }>;
    required: string[];
  };
}

/** Every governed tool takes an intent_ref: the work order the call claims to
 *  act under. REMORA resolves it against the signed intent source; an
 *  unresolvable or mismatched reference is what turns a plausible call into an
 *  ESCALATE rather than a silent success. */
const INTENT: Record<string, { type: string; description: string }> = {
  intent_ref: {
    type: "string",
    description:
      "The work order this call acts under, e.g. WO-1201 or MON-ROUND. " +
      "Required: a call with no resolvable intent has no authority behind it.",
  },
};

export const TOOLS: GovernedTool[] = [
  {
    name: "read_sensor",
    description:
      "Read one process sensor. Read-only, but still governed: the reading is " +
      "only returned when the call resolves under a valid intent.",
    inputSchema: {
      type: "object",
      properties: {
        sensor_id: { type: "string", description: "Sensor tag, e.g. PT-101." },
        ...INTENT,
      },
      required: ["sensor_id", "intent_ref"],
    },
  },
  {
    name: "adjust_setpoint",
    description:
      "Change a control loop setpoint. Mutating and physically consequential; " +
      "expect approval to be required before it executes.",
    inputSchema: {
      type: "object",
      properties: {
        loop: { type: "string", description: "Control loop tag, e.g. PIC-101." },
        value: { type: "number", description: "New setpoint value." },
        ...INTENT,
      },
      required: ["loop", "value", "intent_ref"],
    },
  },
  {
    name: "set_valve_position",
    description:
      "Set a valve position in percent. Mutating and physically consequential; " +
      "expect approval to be required before it executes.",
    inputSchema: {
      type: "object",
      properties: {
        valve: { type: "string", description: "Valve tag, e.g. V-12." },
        position_pct: { type: "number", description: "Position, 0-100." },
        ...INTENT,
      },
      required: ["valve", "position_pct", "intent_ref"],
    },
  },
  {
    name: "acknowledge_alarm",
    description: "Acknowledge an active process alarm.",
    inputSchema: {
      type: "object",
      properties: {
        alarm_id: { type: "string", description: "Alarm tag, e.g. LT-410-HI." },
        ...INTENT,
      },
      required: ["alarm_id", "intent_ref"],
    },
  },
  {
    name: "create_work_order",
    description: "Create a work order.",
    inputSchema: {
      type: "object",
      properties: {
        wo_id: { type: "string", description: "Work order id, e.g. WO-1310." },
        ...INTENT,
      },
      required: ["wo_id", "intent_ref"],
    },
  },
  {
    name: "close_work_order",
    description: "Close an existing work order.",
    inputSchema: {
      type: "object",
      properties: {
        wo_id: { type: "string", description: "Work order id, e.g. WO-1201." },
        ...INTENT,
      },
      required: ["wo_id", "intent_ref"],
    },
  },
];

/** Not a governed tool: it changes nothing. It reports where a proposal that
 *  needed human approval has got to, and executes it once approval exists. */
export const STATUS_TOOL: GovernedTool = {
  name: "remora_proposal_status",
  description:
    "Check a proposal that returned pending_approval. While it is still " +
    "pending this reports that and nothing happens. Once a human has " +
    "approved it, this executes the call exactly as proposed and returns the " +
    "result. The arguments cannot be changed between approval and execution.",
  inputSchema: {
    type: "object",
    properties: {
      proposal_id: {
        type: "string",
        description: "The proposal_id returned by the governed tool call.",
      },
    },
    required: ["proposal_id"],
  },
};

export const ALL_TOOLS: GovernedTool[] = [...TOOLS, STATUS_TOOL];
export const GOVERNED_NAMES = new Set(TOOLS.map((t) => t.name));
