@echo off

REM 1) Depending on cluster or testing system, need to change drive letter
set "SLICER_EXE=E:\slicer\Slicer.exe"
set "PYTHON_SCRIPT=E:\run.py"
set "READY_FILE=%TEMP%\slicer_ready_%RANDOM%.txt"

REM 2) Remove any previous file
if exist "%READY_FILE%" del "%READY_FILE%"

ping -n 2 127.0.0.1 > nul

if [%1]==[] goto justRunSlicer
@echo Run Slicer and load file

start "" "%SLICER_EXE%" --no-splash --python-script %PYTHON_SCRIPT% -i %1 -r %READY_FILE%
goto :showLoadingScreen
s
:justRunSlicer
start "" "%SLICER_EXE%" --no-splash --python-script %PYTHON_SCRIPT% -r %READY_FILE%
goto :showLoadingScreen
s

:showLoadingScreen
powershell -NoLogo -NoProfile -STA -WindowStyle Hidden -Command ^
  "Add-Type -AssemblyName System.Windows.Forms; " ^
  "Add-Type -AssemblyName System.Drawing; " ^

  "$StartTime = $(get-date);" ^

  "$form = New-Object Windows.Forms.Form; " ^
  "$form.WindowState = 'Maximized'; " ^
  "$form.FormBorderStyle = 'None'; " ^
  "$form.BackColor = [Drawing.Color]::FromArgb(0,188,242); " ^
  "$form.Opacity = 1.0; " ^
  "$form.TopMost = $true; " ^
  "$form.KeyPreview = $true; " ^

  "$label = New-Object Windows.Forms.Label; " ^
  "$label.Text = 'Loading SlicerHeart Viewer ...'; " ^
  "$label.ForeColor = [Drawing.Color]::White; " ^
  "$label.Font = New-Object Drawing.Font('Segoe UI', 48, [Drawing.FontStyle]::Bold); " ^
  "$label.AutoSize = $true; " ^
  "$form.Controls.Add($label); " ^
  "$label.TextAlign = 'MiddleCenter'; " ^

  "$centerLabel = { " ^
  "    $form.PerformLayout(); " ^
  "    $label.Left = [Math]::Round(($form.ClientSize.Width - $label.Width) / 2); " ^
  "    $label.Top  = [Math]::Round(($form.ClientSize.Height - $label.Height) / 2); " ^
  "}; " ^

  "$form.Add_Shown($centerLabel); " ^
  "$form.Add_Resize($centerLabel); " ^
  "$form.Add_KeyDown({ if ($_.KeyCode -eq 'Escape') { $form.Tag = 'ESC'; $form.Close() } }); " ^

  "$form.Show(); " ^
  "$minVisible = (Get-Date).AddSeconds(3); " ^
  "$spinner = '.','..','...','....'; " ^
  "$i = 0; " ^

  "[void][System.Windows.Forms.Application]::DoEvents(); " ^
  "while (-not (Test-Path '%READY_FILE%') -and $form.Tag -ne 'ESC') { " ^
  "  $elapsedTime = $(get-date) - $StartTime; " ^
  "  $totalTime = '{0:mm:ss}' -f ([datetime]$elapsedTime.Ticks); " ^
  "  $label.Text = 'Loading SlicerHeart Viewer ' + [System.Environment]::NewLine + $totalTime; " ^
  "  $label.Refresh(); " ^
  "  $i++; " ^
  "  Start-Sleep -Milliseconds 500; " ^
  "  [void][System.Windows.Forms.Application]::DoEvents(); " ^
  "}; " ^
  "while ((Get-Date) -lt $minVisible) { Start-Sleep -Milliseconds 100; [void][System.Windows.Forms.Application]::DoEvents(); }; " ^
  "$form.Close();"
