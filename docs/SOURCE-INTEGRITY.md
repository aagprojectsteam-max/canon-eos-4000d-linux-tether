# Source integrity

The repository keeps a readable application source at `app/aag_canon.py` and a byte-exact, camera-tested v1.1.0 production payload in five small files under `app/canonical/`.

During installation the five payload parts are concatenated, base64-decoded, gunzipped, SHA-256 verified against the materialized production source, syntax-checked, and installed as the runtime `aag_canon.py`.

Canonical production source SHA-256:

`5e3843a1f70e98eb70e11fe9ee521968625484188d56ca6617cb263bb128824b`

The compressed representation is deliberately not treated as the identity because gzip metadata such as timestamps can vary while materializing identical source bytes. The materialized source hash above is the authority.

GitHub Actions performs the same source-integrity and syntax checks on every push and pull request.
