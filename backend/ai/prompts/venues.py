"""Venue-specific review criteria. To add a venue, add an entry here and to
the `Venue` literal in ai/schemas.py.
"""

VENUE_CRITERIA = {
    "generic": """\
Review against general standards for a scientific paper:
- Claims are supported by evidence in the paper.
- Methods are described in enough detail to reproduce.
- Experiments include appropriate baselines and report variance.
- Writing is clear and well organized.""",

    "neurips": """\
Review as a NeurIPS reviewer:
- Novelty and significance relative to prior ML work are the top priority.
- Expect strong baselines, ablations, and multiple seeds with error bars or confidence intervals.
- Reproducibility: hyperparameters, compute, datasets, and code availability (NeurIPS checklist).
- A limitations section and discussion of broader impact are expected.""",

    "acl": """\
Review as an ACL (NLP) reviewer:
- A dedicated Limitations section is mandatory; flag its absence as critical.
- Expect discussion of ethics, data provenance, and the languages covered.
- Expect comparison to strong, recent NLP baselines and significance testing.
- Report dataset statistics, model sizes, and evaluation details.""",

    "journal": """\
Review as a reviewer for a peer-reviewed journal:
- Expect completeness: thorough related work, full methodology, and complete results.
- Statistical rigor: significance tests, effect sizes, and variance reporting.
- Conclusions must be proportionate to the evidence; flag overgeneralization.
- Clear, polished writing and consistent notation throughout.""",
}
