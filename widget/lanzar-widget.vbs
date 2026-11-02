' Arranca el widget de cuentas de Claude sin ventana de consola (pythonw, estilo 0).
Option Explicit
Dim sh, fso, carpeta
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
carpeta = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = carpeta
sh.Run "pythonw """ & carpeta & "\claude_cuentas.py""", 0, False
