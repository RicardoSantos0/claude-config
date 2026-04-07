# Links ~/.claude/agents and ~/.claude/commands to this repo.
# Run once per machine after cloning (as Administrator for symlinks).

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ClaudeDir = "$env:USERPROFILE\.claude"

function Link-Dir($name) {
  $target = "$RepoDir\$name"
  $link   = "$ClaudeDir\$name"

  if (Test-Path -PathType Container $link) {
    if ((Get-Item $link).LinkType -eq "SymbolicLink") {
      Write-Host "Already linked: $link"
    } else {
      Write-Host "Backing up existing $link -> ${link}.bak"
      Move-Item $link "${link}.bak"
      New-Item -ItemType SymbolicLink -Path $link -Target $target | Out-Null
      Write-Host "Linked: $link -> $target"
    }
  } else {
    New-Item -ItemType SymbolicLink -Path $link -Target $target | Out-Null
    Write-Host "Linked: $link -> $target"
  }
}

Link-Dir "agents"
Link-Dir "commands"
