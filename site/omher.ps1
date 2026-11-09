# omher.app/omher.ps1 - the short form of
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta
# Usage: irm https://omher.app/omher.ps1 | iex
# It runs the OMH installer with omher@beta: Hermes (when missing), OMH, then the
# omher desktop app. It never calls exit, so the window you ran it in stays open.
& ([scriptblock]::Create((Invoke-RestMethod https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta
