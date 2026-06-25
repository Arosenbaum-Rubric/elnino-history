param([int]$Port = 3456)
# Enable TLS 1.2 for all outbound HTTPS requests
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$root = "C:\Users\arosenbaum\Downloads\ELNINO tracker"
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:$Port/")
$listener.Start()
Write-Host "Serving $root on http://localhost:$Port/ (with /proxy/* data routes)"
Write-Host "  /proxy/usda?commodity=CODE  -> USDA FAS PSD world supply/use"
Write-Host "  /proxy/fao?item=CODE&years=Y -> FAO FAOSTAT world production"
Write-Host "  /proxy/oni                   -> NOAA CPC latest ONI"

$mime = @{ ".html"="text/html"; ".js"="application/javascript"; ".css"="text/css";
           ".json"="application/json"; ".png"="image/png"; ".svg"="image/svg+xml" }

function Parse-QS($raw) {
    $h = @{}
    $raw.TrimStart('?').Split('&') | ForEach-Object {
        $p = $_.Split('=', 2)
        if ($p.Length -eq 2) { $h[$p[0]] = [Uri]::UnescapeDataString($p[1]) }
    }
    return $h
}

function Write-Json($res, $json) {
    $res.ContentType = "application/json; charset=utf-8"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $res.OutputStream.Write($bytes, 0, $bytes.Length)
}

function Write-Err($res, $code, $msg) {
    $res.StatusCode = $code
    $safe = $msg -replace '"', "'"
    Write-Json $res "{`"error`":`"$safe`"}"
}

while ($listener.IsListening) {
  try {
    $ctx    = $listener.GetContext()
    $req    = $ctx.Request
    $res    = $ctx.Response
    $res.Headers.Add("Access-Control-Allow-Origin", "*")
    $urlPath = $req.Url.AbsolutePath

    # ── PROXY ROUTES ──────────────────────────────────────────────
    if ($urlPath -like "/proxy/*") {
      try {
        $qs = Parse-QS $req.Url.Query
        $wc = New-Object System.Net.WebClient
        $wc.Headers.Add("Accept", "application/json")
        $wc.Encoding = [System.Text.Encoding]::UTF8

        # USDA FAS PSD — world aggregate (country "00")
        if ($urlPath -eq "/proxy/usda") {
          $code = $qs["commodity"]
          if (!$code) { Write-Err $res 400 "missing commodity"; $res.Close(); continue }
          $url  = "https://apps.fas.usda.gov/psdonline/api/psd/commodity/$code/country/00"
          Write-Host "  PROXY USDA $url"
          $data = $wc.DownloadString($url)
          Write-Json $res $data
        }

        # FAO FAOSTAT — QCL domain, element 5510 (Production, tonnes)
        elseif ($urlPath -eq "/proxy/fao") {
          $item  = $qs["item"]
          $years = $qs["years"]
          if (!$item) { Write-Err $res 400 "missing item"; $res.Close(); continue }
          # Try area_cs=World first; fall back to area=5000 if empty
          $data = $null
          foreach ($areaParam in @("area_cs=World", "area=5000")) {
            try {
              $url  = "https://fenix.fao.org/faostat/api/v1/en/data/QCL?$areaParam&item=$item&element=5510&year=$years&output_type=json"
              Write-Host "  PROXY FAO $url"
              $raw  = $wc.DownloadString($url)
              $obj  = $raw | ConvertFrom-Json
              if ($obj.data -and $obj.data.Count -gt 0) { $data = $raw; break }
            } catch {}
          }
          if ($data) { Write-Json $res $data }
          else { Write-Err $res 502 "FAO returned no data for item $item" }
        }

        # NOAA CPC ONI — parse text, return JSON
        elseif ($urlPath -eq "/proxy/oni") {
          $url = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
          Write-Host "  PROXY ONI $url"
          $raw   = $wc.DownloadString($url)
          $lines = ($raw.Trim() -split '\r?\n') | Where-Object { $_ -match '\S' -and $_ -notmatch '^SEAS' }
          $parts = ($lines[-1].Trim() -split '\s+')
          $json  = "{`"season`":`"$($parts[0])`",`"year`":$($parts[1]),`"val`":$($parts[3]),`"src`":`"NOAA CPC`"}"
          Write-Json $res $json
        }

        else { Write-Err $res 404 "unknown proxy route" }

      } catch {
        Write-Host "  PROXY ERROR: $($_.Exception.Message)"
        Write-Err $res 502 $_.Exception.Message
      }
      $res.Close()
    }

    # ── STATIC FILES ──────────────────────────────────────────────
    else {
      $rel = $req.Url.LocalPath.TrimStart('/')
      if ([string]::IsNullOrEmpty($rel)) { $rel = "index.html" }
      $path = Join-Path $root $rel
      if (Test-Path $path -PathType Leaf) {
        $bytes = [System.IO.File]::ReadAllBytes($path)
        $ext   = [System.IO.Path]::GetExtension($path).ToLower()
        if ($mime.ContainsKey($ext)) { $res.ContentType = $mime[$ext] }
        $res.OutputStream.Write($bytes, 0, $bytes.Length)
      } else {
        $res.StatusCode = 404
      }
      $res.Close()
    }
  } catch { }
}
