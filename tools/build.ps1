param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Debug',
    [string]$ToolchainBin = ''
)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ToolchainBin)) {
    $tool = Get-ChildItem -Path 'C:\ST' -Filter 'arm-none-eabi-gcc.exe' `
        -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like '*gnu-tools-for-stm32*' } |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($null -eq $tool) { throw 'Pass -ToolchainBin with your Arm GNU tools bin directory.' }
    $ToolchainBin = $tool.DirectoryName
}
& python (Join-Path $PSScriptRoot 'build.py') --configuration $Configuration --toolchain-bin $ToolchainBin
if ($LASTEXITCODE -ne 0) { throw 'Firmware build failed.' }
