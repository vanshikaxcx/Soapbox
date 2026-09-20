[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = "help"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script:RequiredVersions = @{
    "Node" = @{ Executable = "node"; Arguments = @("--version"); Expected = "24.21.0" }
    "npm" = @{ Executable = "npm"; Arguments = @("--version"); Expected = "12.0.2" }
    "Python" = @{ Executable = "python"; Arguments = @("--version"); Expected = "3.12.14" }
    "uv" = @{ Executable = "uv"; Arguments = @("--version"); Expected = "0.12.13" }
    "SAM CLI" = @{ Executable = "sam"; Arguments = @("--version"); Expected = "1.164.0" }
}
$script:GitleaksVersion = "8.30.1"
$script:SamBuildImage = "public.ecr.aws/sam/build-python3.12@sha256:6b977f28341c892f743070ef945b600f1b257b668003720dc3bc9b1839fcd666"

function Get-ToolOutput {
    param([string]$Executable, [string[]]$Arguments)
    if ($null -eq (Get-Command $Executable -ErrorAction SilentlyContinue)) {
        return $null
    }
    $output = & $Executable @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Unable to determine $Executable version: $output" }
    return ($output | Out-String).Trim()
}

function Get-SemanticVersion {
    param([string]$Value)
    $match = [regex]::Match($Value, "(?<![0-9])(\d+\.\d+\.\d+)(?![0-9])")
    if (-not $match.Success) { throw "Could not parse a semantic version from '$Value'." }
    return $match.Groups[1].Value
}

function Test-RequiredVersions {
    foreach ($name in $script:RequiredVersions.Keys) {
        $tool = $script:RequiredVersions[$name]
        $rawVersion = Get-ToolOutput -Executable $tool.Executable -Arguments $tool.Arguments
        if ($null -eq $rawVersion) {
            throw "$name is required at exactly $($tool.Expected) but was not found. See README.md for platform prerequisites."
        }
        $observed = Get-SemanticVersion -Value $rawVersion
        Write-Output "${name}: observed $observed; required $($tool.Expected)"
        if ($observed -ne $tool.Expected) {
            throw "$name version mismatch: expected $($tool.Expected), observed $observed. See README.md for platform prerequisites."
        }
    }
}

function Show-Versions {
    Write-Output "Repository root: $script:RepositoryRoot"
    foreach ($name in $script:RequiredVersions.Keys) {
        $tool = $script:RequiredVersions[$name]
        $rawVersion = Get-ToolOutput -Executable $tool.Executable -Arguments $tool.Arguments
        if ($null -eq $rawVersion) {
            Write-Output "${name}: not found; required $($tool.Expected)"
        }
        else {
            Write-Output "${name}: observed $(Get-SemanticVersion -Value $rawVersion); required $($tool.Expected)"
        }
    }
    if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Output "Docker: not found (required only for later build/dev/Gate A commands)"
    }
    else {
        $savedErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $engine = (& docker version --format '{{.Server.Version}}' 2>$null) -join ''
            $engineExitCode = $LASTEXITCODE
            $compose = (& docker compose version --short 2>$null) -join ''
            $composeExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $savedErrorActionPreference
        }
        if ($engineExitCode -eq 0) { Write-Output "Docker Engine: $engine" }
        else { Write-Output "Docker Engine: unavailable" }
        if ($composeExitCode -eq 0) { Write-Output "Docker Compose: $compose" }
        else { Write-Output "Docker Compose: unavailable" }
    }
}

function Get-GitleaksInstallRoot {
    $toolRoot = Join-Path $script:RepositoryRoot ".tools"
    return Join-Path $toolRoot "gitleaks-$script:GitleaksVersion"
}

function Get-GitleaksBinaryPath {
    $binaryName = if ($IsWindows) { "gitleaks.exe" } else { "gitleaks" }
    return Join-Path (Get-GitleaksInstallRoot) $binaryName
}

function Install-Gitleaks {
    $installRoot = Get-GitleaksInstallRoot
    $toolRoot = Split-Path -Parent $installRoot
    $binary = Get-GitleaksBinaryPath

    # Fast path: a binary already verified earlier in this same run/host needs
    # no re-download, re-hash, or re-extraction. `setup` and `security` both
    # call Install-Gitleaks; without this, every run pays that cost twice.
    if (Test-Path -LiteralPath $binary -PathType Leaf) {
        $existingVersionOutput = & $binary version 2>&1
        $existingVersion = $null
        if ($LASTEXITCODE -eq 0) {
            try { $existingVersion = Get-SemanticVersion -Value ($existingVersionOutput | Out-String) }
            catch { $existingVersion = $null }
        }
        if ($existingVersion -eq $script:GitleaksVersion) {
            Write-Output "Gitleaks $script:GitleaksVersion already installed and verified; skipping re-download."
            return
        }
    }

    $platform = if ($IsWindows) { "windows" } elseif ($IsMacOS) { "darwin" } elseif ($IsLinux) { "linux" } else { throw "Unsupported Gitleaks host platform." }
    $architecture = switch ([System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture) {
        "X64" { "x64"; break }
        "Arm64" { "arm64"; break }
        default { throw "Unsupported Gitleaks host architecture." }
    }
    $extension = if ($IsWindows) { "zip" } else { "tar.gz" }
    $archiveName = "gitleaks_{0}_{1}_{2}.{3}" -f $script:GitleaksVersion, $platform, $architecture, $extension
    $checksumsName = "gitleaks_{0}_checksums.txt" -f $script:GitleaksVersion
    $downloadRoot = Join-Path $toolRoot "downloads"
    New-Item -ItemType Directory -Force -Path $downloadRoot, $installRoot | Out-Null
    $archive = Join-Path $downloadRoot $archiveName
    $checksums = Join-Path $downloadRoot $checksumsName
    $release = "https://github.com/gitleaks/gitleaks/releases/download/v$script:GitleaksVersion"
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
        Invoke-WebRequest -Uri "$release/$archiveName" -OutFile $archive
    }
    if (-not (Test-Path -LiteralPath $checksums -PathType Leaf)) {
        Invoke-WebRequest -Uri "$release/$checksumsName" -OutFile $checksums
    }
    $line = Select-String -LiteralPath $checksums -Pattern ([regex]::Escape($archiveName)) | Select-Object -First 1
    if ($null -eq $line) { throw "Published Gitleaks checksums did not include $archiveName." }
    $expectedHash = ([regex]::Match($line.Line, "[A-Fa-f0-9]{64}")).Value.ToLowerInvariant()
    $actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($expectedHash.Length -ne 64 -or $actualHash -ne $expectedHash) {
        # Delete the corrupted cache so the next invocation re-downloads
        # instead of deterministically failing forever on a truncated file.
        Remove-Item -LiteralPath $archive, $checksums -Force -ErrorAction SilentlyContinue
        throw "Gitleaks archive checksum verification failed; the cached download was removed, retry to re-download."
    }
    if ($extension -eq "zip") { Expand-Archive -LiteralPath $archive -DestinationPath $installRoot -Force }
    else {
        & tar -xzf $archive -C $installRoot
        if ($LASTEXITCODE -ne 0) { throw "Unable to extract Gitleaks archive." }
    }
    if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) { throw "Gitleaks archive did not include $(Split-Path -Leaf $binary)." }
    $binaryVersion = & $binary version 2>&1
    if ($LASTEXITCODE -ne 0 -or (Get-SemanticVersion -Value ($binaryVersion | Out-String)) -ne $script:GitleaksVersion) {
        throw "Cached Gitleaks binary did not report the required version $script:GitleaksVersion."
    }
    Write-Output "Gitleaks $script:GitleaksVersion archive checksum and cached binary version verified."
}

function Invoke-Setup {
    Test-RequiredVersions
    Install-Gitleaks
    Push-Location -LiteralPath $script:RepositoryRoot
    try {
        & uv sync --frozen
        if ($LASTEXITCODE -ne 0) { throw "Frozen uv synchronization failed." }
        & npm --prefix web ci
        if ($LASTEXITCODE -ne 0) { throw "Frozen npm installation failed." }
        & npm --prefix web exec playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw "Pinned Playwright Chromium installation failed." }
    }
    finally { Pop-Location }
}

function Get-Stage3Paths {
    return @{
        Contract = Join-Path $script:RepositoryRoot "contracts/openapi.yaml"
        Generated = Join-Path $script:RepositoryRoot "web/src/api/generated/schema.d.ts"
        SubsetCheck = Join-Path $script:RepositoryRoot "scripts/check-openapi-aws-subset.mjs"
        SamTemplate = Join-Path $script:RepositoryRoot "infra/template.yaml"
        Web = Join-Path $script:RepositoryRoot "web"
    }
}

function Invoke-OpenApiSubsetCheck {
    param([hashtable]$Paths)
    & node $Paths.SubsetCheck $Paths.Contract
    if ($LASTEXITCODE -ne 0) { throw "OpenAPI AWS/SAM subset validation failed." }
    & node --test (Join-Path $script:RepositoryRoot "tests/contracts/openapi-contract.test.mjs")
    if ($LASTEXITCODE -ne 0) { throw "OpenAPI transport contract tests failed." }
}

function Invoke-OpenApiGeneration {
    param([hashtable]$Paths)
    $generatedDirectory = Split-Path -Parent $Paths.Generated
    New-Item -ItemType Directory -Force -Path $generatedDirectory | Out-Null
    & npm --prefix $Paths.Web exec -- openapi-typescript $Paths.Contract --output $Paths.Generated
    if ($LASTEXITCODE -ne 0) { throw "Pinned openapi-typescript generation failed." }
    & npm --prefix $Paths.Web exec -- prettier --write $Paths.Generated
    if ($LASTEXITCODE -ne 0) { throw "Pinned Prettier formatting for generated declarations failed." }
}

function Invoke-OpenApiGenerate {
    $paths = Get-Stage3Paths
    Invoke-OpenApiSubsetCheck -Paths $paths
    Invoke-OpenApiGeneration -Paths $paths
    Write-Output "OpenAPI declarations generated at $($paths.Generated)."
}

function Invoke-WithScopedAwsRegion {
    param([ScriptBlock]$ScriptBlock)
    # SAM CLI's boto3 session requires some region value even for fully local
    # operations (validate, local start-api) that make no real AWS calls. Use a
    # scoped placeholder only when the host has none configured; WP-01 owns the
    # real deployment region decision.
    $previousRegion = $env:AWS_DEFAULT_REGION
    if ([string]::IsNullOrEmpty($previousRegion)) { $env:AWS_DEFAULT_REGION = "us-east-1" }
    try {
        & $ScriptBlock
    }
    finally {
        if ([string]::IsNullOrEmpty($previousRegion)) { Remove-Item Env:\AWS_DEFAULT_REGION -ErrorAction SilentlyContinue }
        else { $env:AWS_DEFAULT_REGION = $previousRegion }
    }
}

function Invoke-OpenApiCheck {
    $paths = Get-Stage3Paths
    Invoke-OpenApiSubsetCheck -Paths $paths
    Invoke-WithScopedAwsRegion {
        & sam validate --template-file $paths.SamTemplate
        if ($LASTEXITCODE -ne 0) { throw "SAM template validation failed." }
    }
    Invoke-OpenApiGeneration -Paths $paths
    # Run from the repository root: `uv export --output-file` embeds the exact
    # path it was given into the generated file's own header comment, so this
    # must stay the same repo-root-relative literal the tracked file already
    # contains, not an absolute path, or every run looks like spurious drift.
    Push-Location -LiteralPath $script:RepositoryRoot
    try {
        $requirements = "services/api/requirements.txt"
        & uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file $requirements
        if ($LASTEXITCODE -ne 0) { throw "Locked production requirements export failed." }
        & git diff --exit-code -- $paths.Generated $requirements
        if ($LASTEXITCODE -ne 0) { throw "Generated OpenAPI declarations or SAM requirements have drifted." }
    }
    finally { Pop-Location }
    Write-Output "OpenAPI schema, AWS/SAM subset, SAM wrapper, and generated declarations passed Stage 3 checks."
}

function Invoke-Stage4Format {
    $web = Join-Path $script:RepositoryRoot "web"
    $prettierPaths = @(
        (Join-Path $web "src"),
        (Join-Path $web "package.json"),
        (Join-Path $web "vite.config.ts"),
        (Join-Path $web "tsconfig.json"),
        (Join-Path $web "eslint.config.js"),
        (Join-Path $web "index.html"),
        (Join-Path $script:RepositoryRoot "playwright.config.ts"),
        (Join-Path $script:RepositoryRoot "tests/e2e"),
        (Join-Path $script:RepositoryRoot "contracts/openapi.yaml"),
        (Join-Path $script:RepositoryRoot "package.json")
    )
    & uv run --frozen ruff format services tests
    if ($LASTEXITCODE -ne 0) { throw "Ruff formatting failed." }
    & uv run --frozen ruff check --fix services tests
    if ($LASTEXITCODE -ne 0) { throw "Ruff fixes failed." }
    & npm --prefix $web exec -- prettier --write @prettierPaths
    if ($LASTEXITCODE -ne 0) { throw "Prettier formatting failed." }
}

function Invoke-Stage4FormatCheck {
    $web = Join-Path $script:RepositoryRoot "web"
    $prettierPaths = @(
        (Join-Path $web "src"),
        (Join-Path $web "package.json"),
        (Join-Path $web "vite.config.ts"),
        (Join-Path $web "tsconfig.json"),
        (Join-Path $web "eslint.config.js"),
        (Join-Path $web "index.html"),
        (Join-Path $script:RepositoryRoot "playwright.config.ts"),
        (Join-Path $script:RepositoryRoot "tests/e2e"),
        (Join-Path $script:RepositoryRoot "contracts/openapi.yaml"),
        (Join-Path $script:RepositoryRoot "package.json")
    )
    & uv run --frozen ruff format --check services tests
    if ($LASTEXITCODE -ne 0) { throw "Ruff format check failed." }
    & npm --prefix $web exec -- prettier --check @prettierPaths
    if ($LASTEXITCODE -ne 0) { throw "Prettier format check failed." }
}

function Invoke-Stage4Lint {
    & uv run --frozen ruff check services tests
    if ($LASTEXITCODE -ne 0) { throw "Ruff lint failed." }
    & npm --prefix web run lint
    if ($LASTEXITCODE -ne 0) { throw "ESLint failed." }
}

function Invoke-Stage4Typecheck {
    & uv run --frozen mypy
    if ($LASTEXITCODE -ne 0) { throw "mypy failed." }
    & npm --prefix web run typecheck
    if ($LASTEXITCODE -ne 0) { throw "TypeScript type check failed." }
}

function Invoke-Stage4TestUnit {
    & uv run --frozen python -m pytest tests/unit
    if ($LASTEXITCODE -ne 0) { throw "Python unit tests failed." }
    & npm --prefix web run test
    if ($LASTEXITCODE -ne 0) { throw "Web unit tests failed." }
}

function Invoke-Stage4TestContract {
    & uv run --frozen python -m pytest tests/contracts
    if ($LASTEXITCODE -ne 0) { throw "Python contract tests failed." }
}

function Invoke-Stage4TestIntegration {
    & uv run --frozen python -m pytest tests/integration
    if ($LASTEXITCODE -ne 0) { throw "Python integration tests failed." }
}

function Invoke-Stage4Test {
    Invoke-Stage4TestUnit
    Invoke-Stage4TestContract
    Invoke-Stage4TestIntegration
}

function Invoke-Stage5SamBuild {
    & sam build --template-file (Join-Path $script:RepositoryRoot "infra/template.yaml") --use-container --build-image $script:SamBuildImage
    if ($LASTEXITCODE -ne 0) { throw "Containerized SAM build failed." }
}

function Invoke-Stage5Build {
    & npm --prefix web run build
    if ($LASTEXITCODE -ne 0) { throw "Vite production build failed." }
    Invoke-Stage5SamBuild
}

function Wait-HttpReady {
    param([string]$Url, [int]$TimeoutSeconds, [string]$Name)

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return }
        }
        catch { }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "$Name did not become ready at $Url within $TimeoutSeconds seconds."
}

function Stop-ManagedProcess {
    param([System.Diagnostics.Process]$Process)
    if (-not $Process.HasExited) {
        $Process.Kill($true)
        $Process.WaitForExit(5000) | Out-Null
    }
}

function Invoke-Stage5Dev {
    $vite = $null
    $sam = $null
    try {
        Invoke-Stage5SamBuild
        $vite = Start-Process -FilePath "npm" -ArgumentList @("--prefix", "web", "run", "dev") -WorkingDirectory $script:RepositoryRoot -PassThru
        $sam = Invoke-WithScopedAwsRegion {
            Start-Process -FilePath "sam" -ArgumentList @("local", "start-api", "--template", ".aws-sam/build/template.yaml", "--host", "127.0.0.1", "--port", "3001") -WorkingDirectory $script:RepositoryRoot -PassThru
        }
        Wait-HttpReady -Url "http://127.0.0.1:5173" -TimeoutSeconds 30 -Name "Vite"
        # A cold host has no cached Lambda Runtime Interface Emulator image yet;
        # SAM Local pulls the base image and then builds a function image on top
        # of it on first invocation, which can take a long time on a slow/unstable
        # network. Every subsequent invocation reuses the cached image, so this
        # generous ceiling only ever costs time on a genuine first cold start.
        Wait-HttpReady -Url "http://127.0.0.1:3001/health" -TimeoutSeconds 1200 -Name "SAM Local health API"
        Write-Output "Development baseline: http://127.0.0.1:5173"
        Write-Output "Health API: http://127.0.0.1:3001/health"
        Write-Output "Press Ctrl+C to stop both processes."
        while ($true) {
            if ($vite.HasExited) { throw "Vite exited unexpectedly with code $($vite.ExitCode)." }
            if ($sam.HasExited) { throw "SAM Local exited unexpectedly with code $($sam.ExitCode)." }
            Start-Sleep -Seconds 1
        }
    }
    finally {
        if ($null -ne $sam) { Stop-ManagedProcess -Process $sam }
        if ($null -ne $vite) { Stop-ManagedProcess -Process $vite }
    }
}

function Invoke-Stage5WebSmoke {
    $previousNodePath = $env:NODE_PATH
    try {
        Invoke-Stage5SamBuild
        $env:NODE_PATH = Join-Path $script:RepositoryRoot "web/node_modules"
        Invoke-WithScopedAwsRegion {
            & npm --prefix web exec -- playwright test
            if ($LASTEXITCODE -ne 0) { throw "Playwright Chromium smoke failed." }
        }
    }
    finally {
        $env:NODE_PATH = $previousNodePath
    }
}

function Get-SuppressionManifestPath {
    return Join-Path $script:RepositoryRoot "security/suppressions.toml"
}

function Get-ActiveSuppressions {
    # Minimal reviewed-suppression manifest parser. The manifest holds only
    # `[[suppression]]` tables with flat string keys; this is intentionally not
    # a general TOML parser, since the schema is small, fixed, and controlled
    # by this repository (see security/suppressions.toml for the schema).
    $manifestPath = Get-SuppressionManifestPath
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Suppression manifest not found at $manifestPath."
    }
    $requiredKeys = @("tool", "id", "scope", "reason", "owner", "approval", "expires")
    $entries = @()
    $current = $null
    foreach ($rawLine in Get-Content -LiteralPath $manifestPath) {
        $line = $rawLine.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { continue }
        if ($line -eq "[[suppression]]") {
            if ($null -ne $current) { $entries += , $current }
            $current = @{}
            continue
        }
        # Supports backslash-escaped quotes/backslashes inside the value, since
        # TOML basic strings allow them (e.g. reason = "a \"vulnerable\" path").
        $match = [regex]::Match($line, '^(\w+)\s*=\s*"((?:[^"\\]|\\.)*)"$')
        if (-not $match.Success) { throw "Unparseable suppression manifest line: $rawLine" }
        if ($null -eq $current) { throw "Suppression manifest key '$($match.Groups[1].Value)' found outside a [[suppression]] table." }
        $unescaped = $match.Groups[2].Value.Replace('\"', '"').Replace('\\', '\')
        $current[$match.Groups[1].Value] = $unescaped
    }
    if ($null -ne $current) { $entries += , $current }

    $enforcedTools = @("pip-audit")
    $documentationOnlyTools = @("gitleaks", "npm-audit")
    $knownTools = $enforcedTools + $documentationOnlyTools
    $today = [DateTime]::UtcNow.Date
    $active = @()
    foreach ($entry in $entries) {
        foreach ($key in $requiredKeys) {
            if (-not $entry.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($entry[$key])) {
                throw "Suppression manifest entry is missing required field '$key'."
            }
        }
        if ($knownTools -notcontains $entry.tool) {
            throw "Suppression '$($entry.id)' names unknown tool '$($entry.tool)'; expected one of: $($knownTools -join ', ')."
        }
        $expiry = [DateTime]::ParseExact($entry.expires, "yyyy-MM-dd", [System.Globalization.CultureInfo]::InvariantCulture)
        if ($expiry.Date -lt $today) {
            throw "Suppression '$($entry.id)' for $($entry.tool) expired on $($entry.expires); remove it or file a newly approved, re-dated entry instead of relying on an expired suppression."
        }
        if ($documentationOnlyTools -contains $entry.tool) {
            Write-Output "Suppression '$($entry.id)' for $($entry.tool) is reviewed documentation only; it does not change $($entry.tool)'s pass/fail behavior (see security/suppressions.toml)."
        }
        $active += , $entry
    }
    # Force array semantics on return: an empty PowerShell array unrolls to zero
    # output objects, which callers would otherwise receive as $null instead of
    # an empty collection.
    return , $active
}

function Test-IgnoreSentinels {
    # Disposable, unmistakably-fake sentinel files under representative
    # .gitignore patterns, proving both that sensitive paths stay ignored and
    # that tracked example templates stay trackable (WP-00 AC-00-19). Every
    # sentinel is created and deleted here; none is ever `git add`ed.
    $sentinelPaths = @(
        ".env.local",
        "raw-audio/FAKE-SENTINEL-DO-NOT-USE.wav",
        "private-evidence/FAKE-SENTINEL-DO-NOT-USE.txt",
        ".aws-sam/build/FAKE-SENTINEL-DO-NOT-USE.txt",
        ".tools/FAKE-SENTINEL-DO-NOT-USE.txt"
    )
    $trackedTemplatePaths = @(
        ".env.example",
        "web/.env.example"
    )
    $created = @()
    $createdDirectories = @()
    Push-Location -LiteralPath $script:RepositoryRoot
    try {
        foreach ($relativePath in $sentinelPaths) {
            $fullPath = Join-Path $script:RepositoryRoot $relativePath
            $directory = Split-Path -Parent $fullPath
            if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
                New-Item -ItemType Directory -Force -Path $directory | Out-Null
                $createdDirectories += , $directory
            }
            Set-Content -LiteralPath $fullPath -Value "FAKE-SENTINEL-DO-NOT-USE: disposable ignore-rule test content, not a real secret." -NoNewline
            $created += $fullPath
            & git check-ignore --quiet -- $relativePath
            $checkIgnoreExitCode = $LASTEXITCODE
            if ($checkIgnoreExitCode -eq 1) {
                throw "Ignore-rule sentinel check failed: expected '$relativePath' to be ignored by .gitignore, but git check-ignore reported it is not."
            }
            elseif ($checkIgnoreExitCode -ne 0) {
                throw "Ignore-rule sentinel check failed: 'git check-ignore -- $relativePath' exited $checkIgnoreExitCode, a fatal git error rather than a not-ignored result."
            }
        }
        foreach ($relativePath in $trackedTemplatePaths) {
            $fullPath = Join-Path $script:RepositoryRoot $relativePath
            if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
                throw "Ignore-rule sentinel check failed: expected tracked example template '$relativePath' to exist."
            }
            & git check-ignore --quiet -- $relativePath
            if ($LASTEXITCODE -eq 0) {
                throw "Ignore-rule sentinel check failed: expected tracked example template '$relativePath' to remain trackable, but git check-ignore reported it is ignored."
            }
        }
        Write-Output "Ignore-rule sentinel checks passed: $($sentinelPaths.Count) sensitive sentinel path(s) ignored, $($trackedTemplatePaths.Count) tracked example template(s) confirmed trackable."
    }
    finally {
        foreach ($fullPath in $created) {
            Remove-Item -LiteralPath $fullPath -Force -ErrorAction SilentlyContinue
        }
        foreach ($directory in ($createdDirectories | Sort-Object -Property Length -Descending)) {
            if ((Test-Path -LiteralPath $directory -PathType Container) -and -not (Get-ChildItem -LiteralPath $directory -Force -ErrorAction SilentlyContinue)) {
                Remove-Item -LiteralPath $directory -Force -ErrorAction SilentlyContinue
            }
        }
        Pop-Location
    }
}

function Invoke-Stage6Security {
    Install-Gitleaks
    $gitleaksBinary = Get-GitleaksBinaryPath
    $activeSuppressions = Get-ActiveSuppressions
    $pipAuditIgnoreArgs = @()
    foreach ($entry in $activeSuppressions) {
        if ($entry.tool -eq "pip-audit") { $pipAuditIgnoreArgs += @("--ignore-vuln", $entry.id) }
    }
    Push-Location -LiteralPath $script:RepositoryRoot
    try {
        # --log-opts="HEAD" scopes the git-history walk to HEAD's own
        # ancestry. Without it, gitleaks' default git-log behavior walks
        # every locally-fetched branch ref (confirmed live 2026-09-20: 20
        # commits scanned with this flag on a clean main checkout vs. ~101
        # without it) -- in CI, a full-history checkout leaves every other
        # contributor's in-progress branches as local refs too, so any
        # secret leaked on someone else's unrelated, unmerged branch fails
        # every PR's security check regardless of what that PR touches.
        # This scopes the check back to what it's actually meant to prove:
        # this branch's own history is clean, not the whole repository's.
        & $gitleaksBinary detect --source . --redact --log-opts="HEAD" --exit-code 1
        if ($LASTEXITCODE -ne 0) { throw "Gitleaks detected a potential secret in repository history." }

        & uv run --frozen pip-audit --requirement services/api/requirements.txt @pipAuditIgnoreArgs
        if ($LASTEXITCODE -ne 0) { throw "pip-audit found a finding in services/api/requirements.txt." }

        & uv run --frozen pip-audit @pipAuditIgnoreArgs
        if ($LASTEXITCODE -ne 0) { throw "pip-audit found a finding in the frozen uv development environment." }

        # npm 12's `npm audit` has no clean per-vulnerability CLI suppression
        # flag; a reviewed npm-audit entry in security/suppressions.toml is
        # tracked as documentation of an approved, expiring exception only,
        # and does not change this command's pass/fail behavior.
        & npm --prefix web audit
        if ($LASTEXITCODE -ne 0) { throw "npm --prefix web audit found a finding in web dependencies." }

        Test-IgnoreSentinels
    }
    finally { Pop-Location }
    Write-Output "Gitleaks history scan, pip-audit (production export and frozen development environment), npm audit, and ignore-rule sentinel checks passed with no unreviewed finding."
}

function Assert-CleanTrackedTree {
    param([string]$Context)
    Push-Location -LiteralPath $script:RepositoryRoot
    try {
        $status = & git -C $script:RepositoryRoot status --porcelain
        if ($LASTEXITCODE -ne 0) { throw "Unable to determine Git working tree status." }
    }
    finally { Pop-Location }
    # `git status --porcelain` (without --ignored) never lists ignored paths, so a
    # plain `??` line here is an unignored untracked file, not build output such as
    # .aws-sam/, node_modules/, or .tools/. Only tracked-file changes (any status
    # other than `??`) indicate the check wrote tracked changes.
    $dirtyLines = @($status | Where-Object { $_ -and -not $_.StartsWith("??") })
    if ($dirtyLines.Count -gt 0) {
        $details = ($dirtyLines -join "`n")
        throw "$Context left tracked changes in the working tree:`n$details"
    }
}

function Invoke-VerifyGateA {
    Test-RequiredVersions
    Invoke-OpenApiCheck
    Invoke-Stage4FormatCheck
    Invoke-Stage4Lint
    Invoke-Stage4Typecheck
    Invoke-Stage4Test
    Invoke-Stage6Security
    Invoke-Stage5Build
    Invoke-Stage5WebSmoke
    Assert-CleanTrackedTree -Context "verify-gate-a"
    Write-Output "Gate A: versions, openapi-check, format-check, lint, typecheck, test, security, build, and web-smoke passed with no tracked changes."
}

function Invoke-VerifyCleanClone {
    Assert-CleanTrackedTree -Context "verify-clean-clone precondition (checkout must start clean)"
    Invoke-Setup
    Invoke-VerifyGateA
    Write-Output "verify-clean-clone: setup and Gate A completed from a clean checkout."
}

function Write-CommandHelp {
    @"
ProofPath WP-00 Stage 7 command surface

Usage: pwsh ./scripts/proofpath.ps1 <command>

Available now: help, versions, setup, openapi-generate, openapi-check, format,
format-check, lint, typecheck, test-unit, test-contract, test-integration, test,
build, dev, web-smoke, security, verify-gate-a, verify-clean-clone

security: runs the checksum-verified native Gitleaks history scan, pip-audit
against services/api/requirements.txt and the frozen uv development
environment, npm --prefix web audit, and disposable ignore-rule sentinel
checks against .gitignore; fails on any unreviewed finding. Non-expired
entries in security/suppressions.toml narrowly suppress named pip-audit
findings; an expired entry fails the command instead of silently suppressing.

verify-gate-a: runs all non-mutating version, lock/generation, format, lint,
type, test, security, build, and Chromium smoke checks, then asserts the
working tree has no tracked changes.

verify-clean-clone: rejects an already dirty checkout, then runs setup
followed by verify-gate-a from a documented fresh clone.

None reserved.
"@ | Write-Output
}

switch ($Command.ToLowerInvariant()) {
    "help" { Write-CommandHelp; break }
    "versions" { Show-Versions; break }
    "setup" { Invoke-Setup; break }
    "format" { Invoke-Stage4Format; break }
    "format-check" { Invoke-Stage4FormatCheck; break }
    "lint" { Invoke-Stage4Lint; break }
    "typecheck" { Invoke-Stage4Typecheck; break }
    "test-unit" { Invoke-Stage4TestUnit; break }
    "test-contract" { Invoke-Stage4TestContract; break }
    "test-integration" { Invoke-Stage4TestIntegration; break }
    "test" { Invoke-Stage4Test; break }
    "openapi-generate" { Invoke-OpenApiGenerate; break }
    "openapi-check" { Invoke-OpenApiCheck; break }
    "build" { Invoke-Stage5Build; break }
    "dev" { Invoke-Stage5Dev; break }
    "web-smoke" { Invoke-Stage5WebSmoke; break }
    "security" { Invoke-Stage6Security; break }
    "verify-gate-a" { Invoke-VerifyGateA; break }
    "verify-clean-clone" { Invoke-VerifyCleanClone; break }
    default { Write-CommandHelp; throw "Unknown ProofPath command: $Command" }
}
