# Downloads the public eval documents into corpus/
$ErrorActionPreference = "Stop"
$ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$files = @{
  "faversham_tc_employee_handbook_2024.pdf" = "https://favershamtowncouncil.gov.uk/wp-content/uploads/2024/09/Faversham-Town-Council-Handbook-2024-Updated.pdf"
  "east_dunbartonshire_ict_acceptable_use_policy.pdf" = "https://www.eastdunbarton.gov.uk/media/m2bosl2o/acceptable-use-of-ict-facilities-policy.pdf"
}
foreach ($name in $files.Keys) {
  $out = Join-Path $here $name
  if (Test-Path $out) { Write-Host "already have $name"; continue }
  Write-Host "downloading $name"
  Invoke-WebRequest -UserAgent $ua -OutFile $out -Uri $files[$name]
}
Get-ChildItem $here | Format-Table Name, Length
