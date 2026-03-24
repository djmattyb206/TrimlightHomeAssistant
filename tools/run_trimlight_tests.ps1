param(
    [string]$Config = ".\\tools\\trimlight_test_runner.local.json",
    [string[]]$Scenario
)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptRoot "..")
Set-Location $repoRoot

$argsList = @(".\\tools\\trimlight_test_runner.py", "--config", $Config)
foreach ($item in $Scenario) {
    $argsList += @("--scenario", $item)
}

& python @argsList
exit $LASTEXITCODE
