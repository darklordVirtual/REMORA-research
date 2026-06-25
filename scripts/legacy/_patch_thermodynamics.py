# Author: Stian Skogbrott
# License: Apache-2.0
"""Patch: add estimate_temperature_prior() to thermodynamics.py."""
import pathlib

path = pathlib.Path("remora/thermodynamics.py")
content = path.read_text(encoding="utf-8")

MARKER = "# ---------------------------------------------------------------------------\n# Legacy post-hoc temperature (uses oracle distribution - has D↔T circularity)\n# ---------------------------------------------------------------------------"

NEW_FUNC = '''def estimate_temperature_prior(prompt: str) -> float:
    """Estimate temperature from prompt structure alone - zero dependency on D.

    Unlike :func:`estimate_structural_temperature`, this function has **no
    category prior**: it uses only the two structural signals that can be
    computed from the raw prompt string without any task-domain knowledge.

    Algorithm::

        density       = len(zlib.compress(prompt)) / len(prompt)   # in (0, 1]
        length_factor = min(log1p(len(prompt)) / 10, 1.0)           # in [0, 1]
        T_prior       = density * 0.60 + length_factor * 0.40

    Both signals are in [0, 1]; the weighted sum therefore lives in [0, 1]
    before clamping to [0.05, 2.0].  The formula is intentionally simple so
    that it is easy to audit and replace with an empirically fitted model.

    Returns
    -------
    float
        Structural temperature prior in [0.05, 2.0].
    """
    if not prompt:
        return 0.50  # uninformative prior

    encoded = prompt.encode("utf-8")
    compressed = zlib.compress(encoded, level=9)
    density = len(compressed) / max(len(encoded), 1)
    length_factor = min(math.log1p(len(prompt)) / 10.0, 1.0)

    raw = density * 0.60 + length_factor * 0.40
    return round(max(0.05, min(raw, 2.0)), 6)


'''

assert MARKER in content, "marker not found"
content = content.replace(MARKER, NEW_FUNC + MARKER, 1)
path.write_text(content, encoding="utf-8")
print("thermodynamics.py patched successfully")
