# GTA V PS5 Converter

**Convert GTA V PC Legacy vehicle add-ons for PlayStation 5.**

GTA V PS5 Converter is a free, open-source community project for converting supported custom vehicles, retaining compatible tuning parts, and preparing vehicle packs for **offline Story Mode**.

> **Beta:** Compatibility depends on the vehicle mod. Passing conversion checks does not guarantee that every feature will work correctly in-game.

## Features

- **Vehicle conversion:** Convert supported PC Legacy add-on cars for PS5.
- **Custom tuning:** Keep compatible customization parts and receive warnings about optional parts that could not be converted.
- **Texture processing:** Preserve original texture quality when supported, without silently reducing resolution.
- **Automatic repairs:** Fix supported issues involving materials, textures and vehicle structures.
- **PS5 material references:** Expand the local material library using original game resources supplied by the user.
- **FTP installation:** Send converted packs to a compatible PS5 setup over a local network.
- **Languages:** English, French and Spanish.

## Download

Find the latest Windows application under **[Releases](../../releases)**.

Download `GTAV-PS5-Converter.exe` and launch it. The standalone application is designed to include its runtime and conversion tools. **Original GTA V game files are not included.**

## Getting started

1. Open **GTA V PS5 Converter**.
2. Import the required original PS5 resources from **your own copy of GTA V**.
3. Select a supported **PC Legacy add-on** vehicle mod.
4. Start the conversion and review the result, including any skipped optional parts.
5. Install the converted pack manually or through the app's optional local FTP feature.

## Compatibility

The primary development target is **GTA V PS5 PPSA04263, version 01.010.002**, used with a compatible backport and GTAV Menu setup. Other game versions and environments have not been fully verified.

This project is intended for **offline Story Mode only**, not GTA Online. Some optional parts may be skipped safely, but essential model or material problems will stop the conversion rather than produce a potentially broken pack.

## Frequently asked questions

**Does it support every vehicle?**  No. The converter supports a growing range of PC Legacy add-on vehicles, but every mod is different.

**Will my tuning parts be converted?**  Compatible parts are retained. Any optional parts omitted during conversion are reported.

**Are original game resources included?**  No. Users must import the necessary resources from their own game.

**Can I transfer vehicles to my PS5?**  Yes, with a compatible setup and local FTP access. Manual installation is also possible.

## Community

Suggestions, contributions and bug reports are welcome through **[GitHub Issues](../../issues)**. When reporting a problem, include the application version and relevant diagnostic information, but **do not upload copyrighted game assets, passwords or personal information**.

## Credits

Special thanks to **rangigm** for contributions to the project.

Original conversion engine and tools: **RaringM / [ps5-gtav-menu](https://github.com/RaringM/ps5-gtav-menu)**. Other upstream projects and notices are listed in [`motor/THIRD_PARTY_NOTICES`](motor/THIRD_PARTY_NOTICES).

## Disclaimer and licensing

This is an unofficial community project and is **not affiliated with or endorsed by Rockstar Games, Take-Two Interactive or Sony Interactive Entertainment**. All trademarks remain the property of their owners.

The root [`LICENSE`](LICENSE) covers only code that its authors have the right to license. Third-party code and derived technical data may have separate licensing requirements; see [`motor/LICENSE`](motor/LICENSE) and [`motor/THIRD_PARTY_NOTICES`](motor/THIRD_PARTY_NOTICES). Redistribution permissions for some derived third-party technical data have not been independently confirmed.
