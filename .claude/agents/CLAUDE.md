# OECM Favourability Tool — Claude Code Rules

## Project overview

Multi-criteria territorial analysis tool for identifying OECM candidates
(CBD COP14 decision 14/8). Python + Streamlit. Full specifications in
SPECIFICATIONS.md. Development rules in WINDSURF_RULES.md.

Read both files at the start of every session before taking any action.

---

## Sub-agent routing rules

### Parallel dispatch — ALL conditions must be met
- Tasks are independent (no shared state, no file overlap)
- Clear module boundaries

**Safe parallel pairs:**
- raster-engineer + wdpa-analyst (different module directories)
- config-manager + test-validator (config vs tests)
- wdpa-analyst (representativity + gap) + ui-builder (skeleton only)

### Sequential dispatch — ANY condition triggers
- Task B depends on output of task A
- Shared files or risk of merge conflict
- Scientific logic involved (always sequential)

**Mandatory sequential chains:**
```
config-manager
    → raster-engineer
    → mce-scientist          ← NEVER parallelise this step
    → wdpa-analyst (full)
    → ui-builder (full)
    → test-validator (full suite)
```

### Always delegate — never implement directly
Any task touching these files must use the named agent:

| File / directory                          | Agent            |
|-------------------------------------------|------------------|
| modules/module2_favourability/mce_engine.py       | mce-scientist    |
| modules/module2_favourability/criteria_manager.py | mce-scientist    |
| modules/module2_favourability/raster_preprocessing.py | raster-engineer |
| modules/module1_protected_areas/          | wdpa-analyst     |
| ui/                                       | ui-builder       |
| app.py                                    | ui-builder       |
| config/                                   | config-manager   |
| tests/                                    | test-validator   |

---

## Scientific constraints (non-negotiable)

These rules apply to ALL agents and to any direct implementation:

- **WLC is forbidden.** Only weighted geometric mean or Yager OWA.
- **Geometric mean:** S = Π(criterion_i ^ w_i), Σw_i = 1
- **OWA orness default:** α = 0.25 (near AND logic)
- **No scientific values hardcoded** — all parameters from config/
- **Group order:** D (mask) → A → B → C (strictly enforced)
- **Group C absence** → flag "classical_pa_preferable", not exclusion
- **Provisioning ES** uses Gaussian transformation only
- **Anthropogenic pressure** has dual role — read SPECIFICATIONS.md §4.3
- **Net area** always computed via geometric union, never summed

---

## Phase gates (do not skip)

| Gate | Condition to advance |
|------|---------------------|
| Phase 1 → 2 | generate_synthetic_data.py produces 6 valid GeoTIFFs |
| Phase 2 → 3 | raster tests pass; WDPA loader returns valid GeoDataFrame |
| Phase 3 → 4 | mce_engine analytical tests pass with known reference values |
| Phase 4 → 5 | RI formula verified; gap layers produced as GeoTIFFs |
| Phase 5 → 6 | `streamlit run app.py` runs without error |

---

## Code standards

- Python ≥ 3.10, type hints on all analytical functions
- Numpy-style docstrings for all functions in modules/
- Explicit NoData handling (np.nan) before any raster calculation
- Logging via standard `logging` module, INFO level
- No hardcoded paths — use config/settings.yaml
- All YAML config loaded via pyyaml, validated on load
- Tests use synthetic data only (tests/synthetic_data/)

---

## Model assignment

Main session:    claude-opus-4-5    (complex reasoning, orchestration)
Subagents:       claude-sonnet-4-6  (implementation, set via env var)

```bash
export CLAUDE_CODE_SUBAGENT_MODEL="claude-sonnet-4-6"
claude --model claude-opus-4-5
```

Override for mce-scientist only:
  model: claude-opus-4-5 (defined in agent frontmatter — science-critical)