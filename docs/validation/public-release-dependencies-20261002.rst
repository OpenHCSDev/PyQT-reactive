pyqt-reactive 0.3.25 original publisher dependency closure
========================================================

Owner: Schrodinger. Reviewed base mainbbd926a9426f972342c99a558358df156a01a10d.
User authorizes dependency publication; parent owns PolyStore/OpenHCS installation.
No pyqt-reactive release owner/open release PR found; only openPR8 is Dependabot.
Original render-complete owner's WT remains unchanged; this small isolated source
WT contains no environment. Source qualification is serial CPU0/512MiB/60s.

Actual original CI36882075334 install failure retained in the existing publication
ledger at /home/ts/wt/openhcs-knowledge-declaration-source-376-20261001/docs/validation/
required-runtime-qt-publication-20261002/pyqt-main-ci-failed.log. requirements-ci.txt
forces ZMQRuntime source da854a3639f5fb2bf85d33773923e24cb3411993, whose ORIGINAL
pyproject declares0.2.19; pyqt-reactive's authoritative project requirement is
>=0.3.0,<0.4. Installer ResolutionImpossible happens before source tests.

Delete that stale override so the original publisher's existing pip install
resolves the authoritative PUBLIC project dependency after ZMQRuntime0.3.0 reaches
the normal index. Preserve the independent ObjectState candidate unchanged.
No publisher/workflow, version, import, runtime behavior or package API change.
No shim, API negotiation, source pin replacement or registry/cache is introduced.

Original unconditional tests/test_window_snapshot_bindings.py imports QtPy/Vispy;
these are missing from the original dev dependency declarations. Declare them in
the existing dev extra used by the original publisher, not an extra pip command,
skip or mocked substitute. Frozen read-only environment has QtPy2.4.3/Vispy0.15.2.
That declaration-gap proof is separate from the observed CI resolver failure.

Existing original release-readiness project_metadata owns PEP621 decoding in the
new three-case dependency guard. Original declarations:3failed. Repair plus
existing immutable-publisher controls:6passed. No behavior/assertion weakened.
Prior bounded source controls:12passed/32deselected,0.58s/71872KiB, exercising
background launch policy and a new capture declaration's comparison behavior.
Exact logs/resources are in the ledger above. No product/native/UI launch,
provider, downloads, installs or private/shared environment mutation.

NRA IMPL-12/13: existing publisher and metadata reader retained, no cloned resolver
or discovery mechanism. TIME-3/4: actual public version declaration replaces the
old incompatible source authority, not a facade or fallback. No algorithm needs
new inheritance; existing owning ancestors and leaf hooks are unchanged.
Adding another direct test dependency needs only the existing dev declaration;
the existing publisher consumes it without a consumer edit. Existing family-level
source controls remain unchanged; no full/global NRA qualification claim.

v0.3.25 is still absent and immutable NEW tag submission follows ordinary reviewed
main integration plus the ZMQ normal-index gate. Original scripts/release.py and
tag-triggered trusted publisher remain the sole publication route. Full artifact
creation/public API verification and parent-installed acceptance remain distinct.
No persisted format changes.
