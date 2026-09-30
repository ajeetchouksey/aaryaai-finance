# One-line install on Windows:
#   irm https://raw.githubusercontent.com/ajeetchouksey/aaryaai-finance/main/scripts/install.ps1 | iex
$ErrorActionPreference = "Stop"
$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py) { Write-Host "Install Python 3.10+ from https://www.python.org/downloads/ (tick 'Add to PATH'), then run this again."; exit 1 }
& $py.Source -m pip install --user --upgrade pipx
& $py.Source -m pipx ensurepath
& $py.Source -m pipx install --force "git+https://github.com/ajeetchouksey/aaryaai-finance"
Write-Host "`nDone. Open a new terminal and run:  aaryaai-finance"
