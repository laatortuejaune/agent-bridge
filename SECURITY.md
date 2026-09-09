# Security

This software reads private local notes and runs through agent lifecycle hooks.
Treat its state directory and configuration backups as sensitive. Never attach
real memory databases, native account configuration, session transcripts or
credential-bearing logs to public issues.

Report vulnerabilities privately to the repository maintainer using GitHub's
private reporting channel when available. Otherwise request a private contact
without publishing exploit details or user data.

The redactor is a defense in depth, not a guarantee that arbitrary secrets will
be detected. The project does not bypass agent authentication or hook trust.
Dependency-free runtime code does not eliminate risk from local hooks, native
format changes, or conflicting configuration writers.
