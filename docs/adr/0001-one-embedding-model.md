# ADR-1: One embedding model

Status: accepted, 2026-10-13.

## Context

Text, images, video frames and audio need comparable vectors for one ranked result list.
Separate captioners, speech recognizers and generative models would add downloads, runtime processes and intermediate text.
ADR-4 records the embeddinggemma-2 Q8_0 and mmproj parity checks on the target host.

## Decision

Use one embedding model, embeddinggemma-2, through the stock llama-server described in ADR-4.
Embed text, images and audio directly. Extract video frames and audio windows before embedding.
Do not add a generative model, ASR model or captioner chain. OCR supplies searchable words for screenshots and rendered pages.

## Consequences

All vectors share one embedding space and one pinned model revision.
Changing the revision requires re-embedding indexed segments.
Audio and image support depend on the parity gates in ADR-4; failing audio can be disabled without adding another model.
