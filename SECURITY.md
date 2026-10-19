# Security policy

Checked on: 2026-10-19.

Docstale runs Git commands, writes `docstale.lock` when you stamp a document,
and keeps hook state under Git metadata. It does not edit agent settings or
execute configured source or documentation paths.

A hook reminder does not authorize edits. For read-only requests, agents must
report affected documents without file edits or stamps.

The optional pi extension runs inside pi with the same operating-system
permissions. It starts only the `docstale` executable from `PATH` or
`DOCSTALE_EXECUTABLE`, with `hook` as its argument. It sends session metadata
through stdin and does not use a shell. Each invocation limits its runtime and
output size. Review the extension before loading it or granting project trust.

Please report suspected command injection, unsafe path handling, unintended file
replacement, or package supply-chain issues privately through GitHub's security
advisory interface. Do not open a public issue until a fix or mitigation is
available.

Before the first public release, only the latest revision of the standalone
repository will receive security fixes. A version support policy will be
documented when releases start.
