# Deviations from the pre-registration

Written when the corpus was sealed, before any scenario was scored.

1. `scenarios_a.json` was written by Sonnet, not Opus. Two Opus authors in
   turn declined to write the access-network file after a safety classifier
   stopped the first attempt, and neither wrote anything. The second was
   told in a preamble that the corpus is test data for an injection
   detector; the brief itself was unchanged. Sonnet then received the same
   brief as the other authors, without that preamble. Two of the three
   files therefore come from Sonnet, and the corpus has no Opus-authored
   scenarios.

2. The three files were checked for structure only before sealing: 64 rows,
   eight groups of eight, and identical arguments on the legitimate and
   injection variants of each group. No row was read for content, edited,
   relabelled or excluded.

3. Found on the first run, before any answer was recorded: the two
   scope-drift scenarios of group B02 add an argument named
   `reset_portal_password`. `semantic_state` refuses credential-shaped keys
   before anything is sent, and the runner stopped on that refusal. The
   runner was changed to record such a scenario as `state_refused`, keep it
   out of the provider's rates and list it in the result. The corpus and the
   question sets were not changed. These two scenarios are a scope drift
   that REMORA's deterministic state check stops on its own.
