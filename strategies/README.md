# strategies/

Generated Hypothesis strategies, one subdirectory per target (`json-parson/`, `toml-tomlc99/`), one
file per agentic-loop iteration within each (`iteration_0.py` through `iteration_N.py`, plus
`final.py` — the winning iteration, copied verbatim). Files are never overwritten, so the evolution
across iterations (Step 4's "log of how it evolved") is reviewable file-by-file alongside `logs/`.
