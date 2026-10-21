# Windows portable paketo atkūrimas

Galutiniam naudotojui skirtas `BackUp_Studio_Windows_x64.zip`: išskleisti ir
paleisti `BackUpStudio.exe`. Šios kūrimo priemonės reikalingos tik kūrėjui.

## Pakavimas Linux aplinkoje

Reikia Python 3.10+, `gcc-mingw-w64-x86-64-posix` ir `msitools`.
`app.ico`, paleidiklio C kodas, manifestas ir resursai yra šiame aplanke.

```sh
python3 packaging/build_portable.py --cache ../packaging-cache --output ../dist
```

Jei Debian / Ubuntu kūrimo paketai išskleisti lokaliai, nurodykite jų šaknį:

```sh
python3 packaging/build_portable.py --tools-root ../packaging-tools --cache ../packaging-cache --output ../dist
```

Kūrimo skriptas atsisiunčia du konkrečius oficialius Python.org failus,
patikrina įtvirtintas SHA-256 sumas, išskleidžia reikalingus komponentus ir
sukompiliuoja Windows PE32+ GUI paleidiklį. MSI tik išskleidžiamas; niekas
neįdiegiama galutinio naudotojo kompiuteryje. Tcl/Tk scenarijai iš oficialių
ZIP išskleidžiami ir pasirenkami absoliučiais keliais.

Rezultatas: `dist/BackUp_Studio_Windows_x64.zip` ir `dist/BackUpStudio`.
Pakartotiniam kūrimui pasirinkite naują išvesties aplanką arba pirmiau
perkelkite seną `dist/BackUpStudio`.

## Paleidimo struktūra

- `BackUpStudio.exe` įkelia tik gretimą `_internal/python314.dll` ir kviečia
  viešą `Py_Main` API. Atskiro terminalo ar Python proceso neatidaro.
- `python314._pth` ir `-I` izoliuoja importus nuo sistemos Python, registro,
  vartotojo paketų bei `PYTHONPATH`. `-B` neleidžia rašyti bytecode į paketą.
- Python kodas yra `_internal/app`; Tcl/Tk DLL – `_internal/DLLs`.
- `portable_bootstrap.py` nustato Tcl/Tk vietas, lango identitetą ir žurnalą.
- Manifestas prašo įprastų vartotojo teisių (`asInvoker`).
- Pakete paliktos originalios bibliotekų licencijos ir failų SHA-256 sąrašas.

## Patikros ribos

Statinė PE/importų patikra neįrodo veikimo konkrečiame Windows kompiuteryje.
Prieš platinant kaip patikrintą Windows leidimą, švarioje Windows 10/11 x64
aplinkoje be įdiegto Python paleiskite EXE, demonstraciją ir `--self-test`.
Patikrinkite kelią su tarpais bei lietuviškomis raidėmis, įprastą vartotoją,
kopijavimą ir atkūrimą su laikinais failais. Naudotojo duomenų tam nereikia.

EXE nėra pasirašytas sertifikatu. Komponentų parašai iš originalių binarinių
failų nešalinami; paleidiklio leidėjo pasirašymas yra atskiras platinimo žingsnis.
