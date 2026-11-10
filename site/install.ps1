# omher.app/install.ps1 - the short form of
#   irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
# Usage: irm https://omher.app/install.ps1 | iex
# It runs the OMH installer with only the arguments you pass (none under
# `irm | iex`), so it installs the OMH command exactly as install.ps1 does. It
# never calls exit, so the window you ran it in stays open; a failed install
# leaves its exit code in $LASTEXITCODE.
& ([scriptblock]::Create((Invoke-RestMethod https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) @args
