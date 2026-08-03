!macro NSIS_HOOK_POSTINSTALL
  ; Create visible shortcuts and launch the app after installation.
  CreateDirectory "$SMPROGRAMS\Материалы встреч"
  CreateShortCut "$DESKTOP\Материалы встреч.lnk" "$INSTDIR\meeting-documents.exe"

  CreateShortCut "$SMPROGRAMS\Материалы встреч\Материалы встреч.lnk" "$INSTDIR\meeting-documents.exe"
  ExecShell "open" "$INSTDIR\meeting-documents.exe"
!macroend
