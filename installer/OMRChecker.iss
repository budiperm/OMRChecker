; Inno Setup script for the OMRChecker Windows installer.
; Built by .github/workflows/release.yml:
;   iscc /DAppVersion=0.6.0 /DSourceDir=..\dist-installer\OMRChecker installer\OMRChecker.iss
; SourceDir is the PyInstaller one-folder build; everything the program needs is
; inside it, so installing downloads nothing.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist-installer\OMRChecker"
#endif
#ifndef NoticesFile
  #define NoticesFile "..\PEMBERITAHUAN-PIHAK-KETIGA.txt"
#endif
#define AppPublisher "Budi Permadi"
#define AppName "OMRChecker - Pemindai LJK"
#define AppExe "OMRChecker.exe"

[Setup]
; AppId identifies the program for upgrades and uninstall: never change it.
AppId={{1BDC713C-1998-4656-9A3D-3D749A5AEDE9}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/budiperm/OMRChecker
AppSupportURL=https://github.com/budiperm/OMRChecker/issues
AppCopyright=Hak cipta (c) 2026 {#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup
DefaultDirName={autopf}\OMRChecker
DefaultGroupName=OMRChecker
DisableProgramGroupPage=yes
; Admin install into Program Files by default; users without admin rights can
; choose "install for me only" instead.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=LISENSI.txt
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
OutputDir=..\dist-installer
OutputBaseFilename=OMRChecker-Setup-{#AppVersion}
ShowLanguageDialog=auto

[Languages]
; Indonesian.isl: unofficial translation from jrsoftware/issrc tag is-6_4_3
Name: "id"; MessagesFile: "Indonesian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\samples\*"; DestDir: "{app}\samples"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\PANDUAN.pdf"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\PERSYARATAN.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "LISENSI.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#NoticesFile}"; DestDir: "{app}"; DestName: "PEMBERITAHUAN-PIHAK-KETIGA.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Panduan OMRChecker"; Filename: "{app}\PANDUAN.pdf"
Name: "{group}\{cm:UninstallProgram,OMRChecker}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,OMRChecker}"; Flags: nowait postinstall skipifsilent

; Templates, settings and crash.log live in %APPDATA%\OMRChecker and are kept on
; uninstall, so reinstalling or upgrading does not lose the user's templates.
