# Author: Stian Skogbrott
# License: Apache-2.0
"""Patch: add supplemental heuristics to ast_guard.py."""
import pathlib

path = pathlib.Path("remora/safety/ast_guard.py")
content = path.read_text(encoding="utf-8")

OLD = "from remora.agent_hook.shell_ast import has_destructive_intent as _hdi"
NEW = (
    "import re as _re\n"
    "\n"
    "from remora.agent_hook.shell_ast import has_destructive_intent as _hdi\n"
    "\n"
    "\n"
    "# -- supplemental heuristics (run regardless of bashlex availability) ---------\n"
    "\n"
    "_SUPPLEMENT_PATTERNS = [\n"
    "    # rm with -f flag alone (force-delete; -rf caught by shell_ast)\n"
    r'    _re.compile(r"\brm\s+[^|;&\n]*-[a-zA-Z]*f", _re.IGNORECASE),' + "\n"
    "    # sudo or su at the start of a command\n"
    r'    _re.compile(r"^\s*(sudo|su)\s", _re.IGNORECASE),' + "\n"
    "    # sudo/su after a semicolon\n"
    r'    _re.compile(r";\s*(sudo|su)\s"),' + "\n"
    "]\n"
    "\n"
    "\n"
    "def _supplemental_heuristics(command):\n"
    "    for pattern in _SUPPLEMENT_PATTERNS:\n"
    "        if pattern.search(command):\n"
    "            return True\n"
    "    return False\n"
)

assert OLD in content, "import marker not found"
content = content.replace(OLD, NEW, 1)

OLD2 = "    destructive, _ = _hdi(command)\n    if destructive:\n        return False"
NEW2 = (
    "    if _supplemental_heuristics(command):\n"
    "        return False\n"
    "\n"
    "    destructive, _ = _hdi(command)\n"
    "    if destructive:\n"
    "        return False"
)

assert OLD2 in content, "parse_and_validate body not found"
content = content.replace(OLD2, NEW2, 1)

path.write_text(content, encoding="utf-8")
print("ast_guard.py patched successfully")
