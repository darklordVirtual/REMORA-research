---
name: Bug report
about: Incorrect behaviour, test failure, or result discrepancy
title: "[BUG] "
labels: bug
assignees: ''
---

**Describe the bug**
A clear description of what is wrong.

**To reproduce**
```bash
# Minimal reproduction
pip install -e .
python -c "..."
```

**Expected behaviour**
What should happen.

**Actual behaviour**
What actually happens. Include full tracebacks.

**Result discrepancy (if applicable)**
If a benchmark result differs from the committed artifact, paste both:
- Expected (from `results/`):
- Observed:

**Environment**
- OS:
- Python version:
- REMORA version (`pip show remora`):
