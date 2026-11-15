<#
.SYNOPSIS
    Apply all ZeoAuction PostgreSQL initialization scripts to Neon.

.DESCRIPTION
    The local PostgreSQL image automatically runs the SQL files in this directory,
    but an external Neon database does not. This script uses a disposable PostgreSQL
    client container and reads NEON_DB_CONNECTION_STRING or DATABASE_URL from the
    process environment, falling back to the repository .env file.

    Run this once against a fresh Neon database. The SQL files are intentionally
    ordered by filename and are not a repeatable migration system.
#>

[CmdletBinding()]
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match "^\s*$([regex]::Escape($Name))\s*=\s*(.*)\s*$") {
            $value = $Matches[1].Trim()
            if ($value.Length -ge 2) {
                $first = $value.Substring(0, 1)
                $last = $value.Substring($value.Length - 1, 1)
                if (($first -eq '"' -and $last -eq '"') -or
                    ($first -eq "'" -and $last -eq "'")) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
            }
            return $value
        }
    }

    return $null
}

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$dotenvPath = Join-Path $repositoryRoot ".env"
$connectionString = $env:NEON_DB_CONNECTION_STRING

if ([string]::IsNullOrWhiteSpace($connectionString)) {
    $connectionString = Get-DotEnvValue -Path $dotenvPath -Name "NEON_DB_CONNECTION_STRING"
}
if ([string]::IsNullOrWhiteSpace($connectionString)) {
    $connectionString = $env:DATABASE_URL
}
if ([string]::IsNullOrWhiteSpace($connectionString)) {
    $connectionString = Get-DotEnvValue -Path $dotenvPath -Name "DATABASE_URL"
}
if ([string]::IsNullOrWhiteSpace($connectionString)) {
    throw "Set NEON_DB_CONNECTION_STRING or DATABASE_URL in the environment or .env file."
}

if ($connectionString -notmatch "^postgres(?:ql)?://") {
    throw "The database connection string must use the postgres:// or postgresql:// scheme."
}

$sqlFiles = Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*.sql" |
    Sort-Object Name
if ($sqlFiles.Count -eq 0) {
    throw "No SQL initialization files were found in $PSScriptRoot."
}

if ($DryRun) {
    Write-Host "Dry run: $($sqlFiles.Count) SQL files found."
    Write-Host "Dry run: connection string loaded without displaying its value."
    exit 0
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is not running."
}

 $stagingDirectory = Join-Path ([System.IO.Path]::GetTempPath()) "zeo-neon-init-$PID"
try {
    New-Item -ItemType Directory -Path $stagingDirectory -Force | Out-Null
    $rolePassword = "$([guid]::NewGuid().ToString('N'))A7!"

    foreach ($sqlFile in $sqlFiles) {
        $stagedFile = Join-Path $stagingDirectory $sqlFile.Name
        if ($sqlFile.Name -eq "00-roles-and-schemas.sql") {
            $contents = Get-Content -LiteralPath $sqlFile.FullName -Raw
            $contents = [regex]::Replace(
                $contents,
                "CREATE ROLE\s+(\w+)\s+LOGIN PASSWORD '[^']*';",
                {
                    param($match)
                    $roleName = $match.Groups[1].Value
                    $dollar = [char]36
                    "DO $dollar$dollar BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$roleName') THEN CREATE ROLE $roleName LOGIN PASSWORD '$rolePassword'; ELSE ALTER ROLE $roleName PASSWORD '$rolePassword'; END IF; END $dollar$dollar;"
                }
            )
            $contents = $contents -replace "CREATE SCHEMA (\w+);", "CREATE SCHEMA IF NOT EXISTS `$1;"
            $contents = $contents -replace "CREATE FUNCTION public\.", "CREATE OR REPLACE FUNCTION public."
            Set-Content -LiteralPath $stagedFile -Value $contents -NoNewline
        } else {
            Copy-Item -LiteralPath $sqlFile.FullName -Destination $stagedFile
        }
    }

    $mount = "type=bind,source=$stagingDirectory,target=/init,readonly"
    foreach ($sqlFile in $sqlFiles) {
        Write-Host "Applying $($sqlFile.Name)"
        $dockerArgs = @(
            "run", "--rm",
            "--env", "DATABASE_URL=$connectionString",
            "--mount", $mount,
            "postgres:15-alpine",
            "psql", $connectionString,
            "-v", "ON_ERROR_STOP=1",
            "-f", "/init/$($sqlFile.Name)"
        )

        & docker @dockerArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Neon initialization failed while applying $($sqlFile.Name)."
        }
    }
} finally {
    if (Test-Path -LiteralPath $stagingDirectory) {
        Remove-Item -LiteralPath $stagingDirectory -Recurse -Force
    }
}

Write-Host "Neon initialization completed successfully."
