# Private evaluator boundary

Place evaluator-only specifications, hidden tests, and gold data outside the runtime data root. This directory is ignored by Git except for this boundary note. The runtime must not mount or read it; evaluation begins only after a run is sealed.
