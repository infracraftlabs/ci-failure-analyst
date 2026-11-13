# Demo output (real AI run)

- Date: 2026-11-14
- Model: qwen3:8b (Ollama, local, Q4_K_M), temperature 0, cianalyst 0.1.0
- Input files: `examples/logs/gha-npm-dependency.log`, `examples/logs/gha-docker-out-of-disk.log` (synthetic)
- Result: 6 causes kept, 0 dropped by the evidence check, 1 confidence capped from high to medium (its quotes did not include the line the rules matched).

One recorded run; language-model output varies.

Below is the exact terminal output (stdout and stderr) of each command.

## `cianalyst --file examples/logs/gha-npm-dependency.log`

````text
$ cianalyst --file examples/logs/gha-npm-dependency.log
### CI failure analysis

**Likely causes (advisory, check before acting)**

- Log: `gha-npm-dependency.log` (GitHub Actions)
- Failing step: `Run npm ci`
- First error: line 60: `npm error code ETARGET`
- Category from rules: **dependency** (rule `npm-resolve`). npm could not resolve a dependency: a version conflict, a version that does not exist, or a lockfile out of sync.

**Summary:** The CI job failed due to an npm dependency resolution error. The error indicates that the package 'chart-widgets-example@^4.0.0' could not be found, which is likely the cause of the failure classified as 'dependency'.

#### Likely causes

1. The package 'chart-widgets-example@^4.0.0' does not exist in the registry, leading to a version mismatch. (confidence: medium)

   ```text
   npm error notarget No matching version found for chart-widgets-example@^4.0.0.
   npm error notarget It was specified as a dependency of 'web-shop'
   ```

2. The version constraint in the package.json might be incorrect or outdated. (confidence: medium)

   ```text
   npm error notarget No matching version found for chart-widgets-example@^4.0.0.
   ```

3. The package might have been renamed or moved, and the dependency is pointing to the wrong name. (confidence: medium)

   ```text
   npm error notarget No matching version found for chart-widgets-example@^4.0.0.
   ```

#### Next checks (text for a person; nothing was run)

- Run `npm install` locally on the same Node.js version and read the conflict it reports.
- Check which recent change touched package.json or package-lock.json.
- Check the peer dependency ranges of the package named in the error.
- (model) Check the package.json file for the 'chart-widgets-example' dependency and verify the version constraint.
- (model) Verify if the package 'chart-widgets-example' still exists in the npm registry or if it has been renamed.
- (model) Ensure that the version specified in the dependency is correct and matches an available version.
- (model) Check if there are any typos in the package name or version in the package.json file.
- (model) Run 'npm install' manually in the same environment to see if the same error occurs.

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

Mode: ai, model: qwen3:8b (local, Ollama). Redactions: none. Causes dropped by the evidence check: 0 (plus 0 quoting suspected injection text). Confidence capped: 1. Unsafe checks dropped: 0.

_Likely causes only, drawn from the log excerpt. Check the evidence before acting; a person decides._
````

## `cianalyst --file examples/logs/gha-docker-out-of-disk.log`

````text
$ cianalyst --file examples/logs/gha-docker-out-of-disk.log
### CI failure analysis

**Likely causes (advisory, check before acting)**

- Log: `gha-docker-out-of-disk.log` (GitHub Actions)
- Failing step: `Run docker build -t registry.example.com/web-shop:3f9a2c1 .`
- First error: line 83: `#12 ERROR: failed to copy files: copy file range failed: no space left on device`
- Category from rules: **infrastructure-runner** (rule `runner-disk-full`). The runner ran out of disk space.
- Other signals: build-compile (compile-error, line 95)

**Summary:** The CI job failed due to a disk space issue, likely caused by the Docker build context being too large or the runner's disk being full. The error message indicates that there is no space left on the device during the COPY step of the Docker build.

#### Likely causes

1. The runner's disk is full. (confidence: high)

   ```text
   #12 ERROR: failed to copy files: copy file range failed: no space left on device
   ERROR: failed to solve: failed to copy files: copy file range failed: no space left on device
   ```

2. The Docker build context is too large. (confidence: medium)

   ```text
   #5 transferring context: 1.21GB 38.4s done
   ```

3. The Docker image is too large to fit on the runner's disk. (confidence: medium)

   ```text
   COPY --from=builder /app ./
   Dockerfile:18
   ```

#### Next checks (text for a person; nothing was run)

- Check free disk space on the runner (for example `df -h`) at the start and end of the job.
- Look for large build caches, Docker images or layers that pile up between steps.
- Prune unused Docker data before the build, or use a runner with a larger disk.
- (model) Check the disk space on the runner using df -h.
- (model) Verify the size of the Docker build context and consider optimizing it.
- (model) Check the size of the Docker image being built and consider using a smaller base image.
- (model) Review the Dockerfile to see if any unnecessary files are being copied.
- (model) Try running the build on a different runner with more disk space.

<details><summary>Log excerpt, lines 50-96 (redacted)</summary>

```text
   50 | ##[group]Run docker build -t registry.example.com/web-shop:3f9a2c1 .
   51 | docker build -t registry.example.com/web-shop:3f9a2c1 .
   52 | shell: /usr/bin/bash -e {0}
   53 | ##[endgroup]
   54 | #0 building with "default" instance using docker driver
   55 | #1 [internal] load build definition from Dockerfile
   56 | #1 transferring dockerfile: 912B done
   57 | #1 DONE 0.0s
   58 | #2 [internal] load metadata for registry.example.com/base/node:22-slim
   59 | #2 DONE 0.6s
   60 | #3 [internal] load .dockerignore
   61 | #3 DONE 0.0s
   62 | #4 [builder 1/6] FROM registry.example.com/base/node:22-slim
   63 | #4 DONE 4.2s
   64 | #5 [internal] load build context
   65 | #5 transferring context: 1.21GB 38.4s done
   66 | #5 DONE 38.5s
   67 | #6 [builder 2/6] WORKDIR /app
   68 | #6 DONE 0.1s
   69 | #7 [builder 3/6] COPY . .
   70 | #7 DONE 21.7s
   71 | #8 [builder 4/6] RUN npm ci
   72 | #8 52.10 added 1412 packages in 51s
   73 | #8 DONE 53.0s
   74 | #9 [builder 5/6] RUN npm run build
   75 | #9 0.412 #9 0.412 > vite build
   76 | #9 44.90 built in 44.12s
   77 | #9 DONE 45.3s
   78 | #10 [builder 6/6] RUN npm prune --omit=dev
   79 | #10 DONE 9.8s
   80 | #11 [runtime 2/4] WORKDIR /app
   81 | #11 DONE 0.1s
   82 | #12 [runtime 3/4] COPY --from=builder /app ./
   83 | #12 ERROR: failed to copy files: copy file range failed: no space left on device
   84 | ------
   85 |  > [runtime 3/4] COPY --from=builder /app ./:
   86 | ------
   87 | Dockerfile:18
   88 | --------------------
   89 |   16 |     FROM registry.example.com/base/node:22-slim AS runtime
   90 |   17 |     WORKDIR /app
   91 |   18 | >>> COPY --from=builder /app ./
   92 |   19 |     USER node
   93 |   20 |     CMD ["node", "dist/server.js"]
   94 | --------------------
   95 | ERROR: failed to solve: failed to copy files: copy file range failed: no space left on device
   96 | ##[error]Process completed with exit code 1.
```

</details>

Mode: ai, model: qwen3:8b (local, Ollama). Redactions: none. Causes dropped by the evidence check: 0 (plus 0 quoting suspected injection text). Confidence capped: 0. Unsafe checks dropped: 0.

_Likely causes only, drawn from the log excerpt. Check the evidence before acting; a person decides._
````
