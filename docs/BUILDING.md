# Building from source

The source tree includes the 1.0.2d startup diagnostics and GUI smoke-test checks.

On a Windows 10/11 x64 build computer, install Python (3.12 preferred) and 7-Zip, then run `BUILD-EXE.bat`. The build script sets up an isolated environment, runs automated tests, bundles the conversion tools and 7-Zip, and tests the resulting executable.

Output: `dist/GTAV-PS5-Converter.exe`.

To run the source directly, use `START-CONVERTER.bat`. End users downloading a standalone EXE do not need this developer workflow.

Game resources are not included in this repository. Review the licenses of all third-party components before distributing binaries.
