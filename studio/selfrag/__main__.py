"""`python -m studio.selfrag` entry point. The logic lives in `cli`, per the
rule that a branch inside an entry point is a branch no test can reach."""

from studio.selfrag.cli import main

raise SystemExit(main())
