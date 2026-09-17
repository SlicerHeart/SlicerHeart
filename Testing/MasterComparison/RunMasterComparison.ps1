<#
Compare the 4D conversion of legacy scenes created with the master branch code.

  .\Testing\MasterComparison\RunMasterComparison.ps1 -Slicer <Slicer.exe> -MasterRepo <master checkout> -OutDir <dir> [-SkipGenerate]

1. GenerateMasterScenes.py runs in a Slicer instance with the SlicerHeart modules of -MasterRepo and
   writes <scenario>.mrb + <scenario>.json (reference values) into -OutDir.
2. CompareConvertedScenes.py runs with the modules of this checkout, converts each scene and writes
   <scenario>-comparison.json and comparison-report.md into -OutDir.
#>
param(
  [Parameter(Mandatory=$true)][string]$MasterRepo,
  [Parameter(Mandatory=$true)][string]$OutDir,
  [Parameter(Mandatory=$true)][string]$Slicer,
  [switch]$SkipGenerate
)

$thisRepo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$modules = @("ValveAnnulusAnalysis", "ValveSegmentation", "ValveQuantification", "Converter4DSequences",
             "ValveBatchExport", "LeafletAnalysis", "ValvePapillaryAnalysis", "CardiacDeviceSimulator")
New-Item -ItemType Directory -Force $OutDir | Out-Null

function Invoke-Slicer([string]$repo, [string]$script, [string]$logName) {
  $paths = $modules | ForEach-Object { Join-Path $repo $_ } | Where-Object { Test-Path $_ }
  $argList = @("--no-splash", "--testing", "--additional-module-paths") + $paths + @("--python-script", $script, "--", $OutDir)
  Write-Host "Running $script with modules of $repo"
  $proc = Start-Process -FilePath $Slicer -ArgumentList $argList -Wait -PassThru `
    -RedirectStandardOutput (Join-Path $OutDir "$logName.stdout.log") -RedirectStandardError (Join-Path $OutDir "$logName.stderr.log")
  Write-Host "  exit code $($proc.ExitCode)"
}

if (-not $SkipGenerate) {
  Invoke-Slicer $MasterRepo (Join-Path $PSScriptRoot "GenerateMasterScenes.py") "generate"
}
Invoke-Slicer $thisRepo (Join-Path $PSScriptRoot "CompareConvertedScenes.py") "compare"
$report = Join-Path $OutDir "comparison-report.md"
if (Test-Path $report) { Get-Content $report } else { Write-Host "No report written, see logs in $OutDir" }
