## Examples

Good example:

- Prompt: $llm-app-dev we are adding an invoice-field extractor that calls a model per upload - set it up so we can change the prompt later without guessing.
- Expected behavior: Name the rails, put the provider call behind one client module with a pinned model ID, declare the extraction schema and the repair path, lay the prompt out as a versioned file, and specify the golden set and validators that let the next prompt edit be compared against this baseline.
- Why: The feature is a real model call whose output another system consumes, which is exactly where an unpinned model, an inline prompt, and a missing golden set become expensive later.

Bad example:

- Prompt: $llm-app-dev the extractor is done - confirm the new prompt is better than the old one.
- Expected behavior: Prepare the paired baseline-vs-candidate comparison and state that no result exists until the run is observed; report nothing about which prompt is better.
- Why: Better is a claim about an observed run. Without one, the comparison is a design, and calling it a result is the false-green this workflow exists to prevent.

Required inputs:

- the feature the model is supposed to perform
- the exact provider and model ID under consideration
- the shape of the output the caller consumes
- the failing cases that must not regress

Artifact expectations:

- prompt files committed under version control with a version identifier the call site records, so a response can be traced to the prompt that produced it
- a golden set committed beside the code as data, not as prose in a chat log
