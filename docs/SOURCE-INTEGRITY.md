# Source integrity

The repository keeps a readable application source at `app/aag_canon.py` and a byte-exact, camera-tested v1.1.0 production payload in five small files under `app/canonical/`.

During installation the five payload parts are concatenated, SHA-256 verified, base64-decoded, gunzipped, SHA-256 verified again, syntax-checked, and installed as the runtime `aag_canon.py`.

Canonical hashes:

- concatenated base64 payload: `d3239d838a5ee0cfb853e7823a7a23c32bca9fd97c140fda8b01471f74b7863a`
- materialized production Python source: `5e3843a1f70e98eb70e11fe9ee521968625484188d56ca6617cb263bb128824b`

GitHub Actions performs the same integrity and syntax checks on every push and pull request.
