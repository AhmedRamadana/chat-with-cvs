function Show-Tree {
    param(
        [string]$Path = ".",
        [string]$Prefix = ""
    )

    $exclude = @("venv", ".venv", "__pycache__", ".git", "node_modules")

    $items = Get-ChildItem -Force -LiteralPath $Path |
        Where-Object { $exclude -notcontains $_.Name } |
        Sort-Object @{Expression = { $_.PSIsContainer }; Descending = $true }, Name

    $count = $items.Count
    for ($i = 0; $i -lt $count; $i++) {
        $item = $items[$i]
        $isLast = ($i -eq $count - 1)
        if ($isLast) { $connector = "+-- " } else { $connector = "|-- " }
        Write-Host "$Prefix$connector$($item.Name)"

        if ($item.PSIsContainer) {
            if ($isLast) { $newPrefix = $Prefix + "    " } else { $newPrefix = $Prefix + "|   " }
            Show-Tree -Path $item.FullName -Prefix $newPrefix
        }
    }
}

Show-Tree -Path "."