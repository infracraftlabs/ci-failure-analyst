### CI failure analysis

**Likely causes (advisory, check before acting)**

- Log: `gha-npm-dependency.log` (GitHub Actions)
- Failing step: `Run npm ci`
- First error: line 60: `npm error code ETARGET`
- Category from rules: **dependency** (rule `npm-resolve`). npm could not resolve a dependency: a version conflict, a version that does not exist, or a lockfile out of sync.

**Summary:** npm ci stopped because no published version of chart-widgets-example matches the requested range ^4.0.0. The project's package.json probably asks for a major version that does not exist on the registry.

#### Likely causes

1. package.json requests chart-widgets-example ^4.0.0, but no version in that range exists on the registry. (confidence: high)

   ```text
   npm error code ETARGET
   No matching version found for chart-widgets-example@^4.0.0.
   ```

2. The dependency is declared directly by the project, so a recent change to package.json is the likely source. (confidence: medium)

   ```text
   It was specified as a dependency of 'web-shop'
   ```

#### Next checks (text for a person; nothing was run)

- Run `npm install` locally on the same Node.js version and read the conflict it reports.
- Check which recent change touched package.json or package-lock.json.
- Check the peer dependency ranges of the package named in the error.
- (model) Check the git history of package.json for the change to chart-widgets-example.
- (model) Run npm view chart-widgets-example versions to see which versions exist.

**Suggested change (model, review before use):** Set chart-widgets-example to a published version range, then run npm install and commit the updated lockfile.

<details><summary>Log excerpt, lines 55-67 (redacted)</summary>

```text
   55 | ##[group]Run npm ci
   56 | npm ci
   57 | shell: /usr/bin/bash -e {0}
   58 | ##[endgroup]
   59 | npm warn config production Use `--omit=dev` instead.
   60 | npm error code ETARGET
   61 | npm error notarget No matching version found for chart-widgets-example@^4.0.0.
   62 | npm error notarget In most cases you or one of your dependencies are requesting
   63 | npm error notarget a package version that doesn't exist.
   64 | npm error notarget
   65 | npm error notarget It was specified as a dependency of 'web-shop'
   66 | npm error notarget
   67 | ##[error]Process completed with exit code 1.
```

</details>

Mode: recorded, model: recorded response (npm-dependency.json). Redactions: none. Causes dropped by the evidence check: 1 (plus 0 quoting suspected injection text). Confidence capped: 0. Unsafe checks dropped: 0.

_Likely causes only, drawn from the log excerpt. Check the evidence before acting; a person decides._
