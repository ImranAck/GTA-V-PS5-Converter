#define AppName "GTA V PS5 Converter"
#define AppVersion "1.0.2c"
#define AppExe "GTAV-PS5-Converter.exe"
[Setup]
AppId={{E4C7ED3E-4797-438A-87E5-599BD3FD742A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=GTA V PS5 Converter contributors
DefaultDirName={localappdata}\Programs\GTAV-PS5-Converter
DefaultGroupName=GTA V PS5 Converter
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=GTAV-PS5-Converter-1.0.2c-Setup-Windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\app.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName} {#AppVersion}
UsePreviousAppDir=yes
CloseApplications=yes
RestartApplications=no
[Files]
Source: "..\dist\GTAV-PS5-Converter.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\motor\THIRD_PARTY_NOTICES"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{autoprograms}\GTA V PS5 Converter"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\GTA V PS5 Converter"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch GTA V PS5 Converter"; Flags: nowait postinstall skipifsilent
