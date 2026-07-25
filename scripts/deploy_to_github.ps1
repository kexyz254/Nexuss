param(
    [string]$RepositoryUrl = "https://github.com/kexyz254/Nexuss.git",
    [string]$Branch = "main",
    [string]$CommitMessage = "chore: establish Nexuss P0 engineering foundation"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' is not installed or not on PATH."
    }
}

Require-Command git

$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("nexuss-deploy-" + [guid]::NewGuid())
$CloneRoot = Join-Path $TempRoot "repo"

try {
    New-Item -ItemType Directory -Path $TempRoot | Out-Null
    git clone $RepositoryUrl $CloneRoot
    if ($LASTEXITCODE -ne 0) { throw "Git clone failed." }

    Push-Location $CloneRoot
    try {
        git show-ref --verify --quiet "refs/remotes/origin/$Branch"

        if ($LASTEXITCODE -eq 0) {
            git checkout -B $Branch "origin/$Branch"
        }
        else {
            # Empty repository: create an unborn initial branch safely.
            git symbolic-ref HEAD "refs/heads/$Branch"
        }

        if ($LASTEXITCODE -ne 0) {
            throw "Could not prepare branch '$Branch'."
        }

        $items = Get-ChildItem -LiteralPath $SourceRoot -Force |
            Where-Object { $_.Name -notin @('.git', '__pycache__') }

        foreach ($item in $items) {
            Copy-Item -LiteralPath $item.FullName -Destination $CloneRoot -Recurse -Force
        }

        Get-ChildItem -LiteralPath $CloneRoot -Recurse -Force -Directory -Filter '__pycache__' |
            Remove-Item -Recurse -Force
        Get-ChildItem -LiteralPath $CloneRoot -Recurse -Force -File -Include '*.pyc','*.pyo' |
            Remove-Item -Force

        if (Test-Path "scripts/validate_repository.py") {
            python scripts/validate_repository.py
            if ($LASTEXITCODE -ne 0) { throw "Repository policy validation failed." }
        }

        if (Get-Command pytest -ErrorAction SilentlyContinue) {
            pytest -q
            if ($LASTEXITCODE -ne 0) { throw "Tests failed; refusing to push." }
        } else {
            Write-Warning "pytest is unavailable; CI must run tests after push."
        }

        git add --all
        $changes = git status --porcelain
        if (-not $changes) {
            Write-Host "No changes to commit. Repository already matches the P0 foundation."
            return
        }

        git commit -m $CommitMessage
        if ($LASTEXITCODE -ne 0) { throw "Git commit failed." }

        git push -u origin $Branch
        if ($LASTEXITCODE -ne 0) { throw "Git push failed." }

        Write-Host "Nexuss P0 successfully deployed to $RepositoryUrl on branch $Branch."
    }
    finally {
        Pop-Location
    }
}
finally {
    if (Test-Path $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    }
}

