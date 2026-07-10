We added webhook signing yesterday.

The HMAC secret lives in env. The SDK wraps it on serialize. The verify endpoint rejects mismatches in 2 ms. PR is up; review by EOD.

Two notes from the run: the timing attack risk is bounded by constant-string comparison, and the failure path returns 401 without the body to avoid leaking signatures.

Next: rotate keys, ship the rotate endpoint, and migrate existing consumers on a 30-day clock.
