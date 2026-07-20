# Intentional unmapped pytest coverage

SpecMason centralizes intentional unmapped coverage in
`specs/behavior/mappings/intentional-unmapped.json`. Each entry names the
pytest node, gives a reviewable reason, and identifies the owning project.

Mapped tests use `specmason` comments and are checked against the normative
requirements manifest. The policy file is the only source for intentional
waivers. Update it when a test becomes observable product behavior, and add a
SpecMason mapping instead of restoring legacy workflow markers.
