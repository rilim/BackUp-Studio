# Windows x64 paketo patikros ataskaita

## Versija 2.6.0 – 2026-10-21

- Kontrolinių sumų indeksas atskiria šaltinio ir kopijos kelius, tikrina failo
  tapatybę, dydį ir laiko žymas. Greitu režimu išsaugotas failas atveriamas ir
  patikrinamas pirmas baitas, todėl naujai blokuojami failai rodomi kaip klaidos.
  Pilnas režimas visus failus perskaito iš naujo.
- Nutraukus skenavimą tas pats mygtukas siūlo naują tikrinimą. Lentelės turinys
  atitrauktas nuo krašto neperstumiant rėmelio.
- Linux: 109 testai, 90 praėjo, 19 GUI praleista, nes nėra grafinio ekrano.
  Tikras Windows EXE paleidimas ir 100 tūkst. failų bandymas Windows aplinkoje
  dar neatlikti. Paketas naudoja pagal manifestą patikrintą ankstesnį EXE.

## Versija 2.5.0 – 2026-10-20

- Visų trijų darbo skilčių vienodas viršutinis išdėstymas ir žemesnės statistikos
  kortelės palieka daugiau vietos failų sąrašui. Kompaktiškumo valdiklis vertina
  tikrą lentelės aukštį; histerezė neleidžia nuolat persijunginėti ties riba.
- Pridėtos įtrauktos failų tipų piktogramos be išorinių priklausomybių ir failų
  turinio skaitymo. Kairiajame Treeview stulpelyje rodomas žymimasis langelis ir
  piktograma; paslėptas duomenų „check“ laukas išlaiko ankstesnį eilučių formatą.
  Stulpelių valdiklis naudoja tikrai rodomus stulpelius, įskaitant #0.
- Linux: 101 testas, iš jų 83 praėjo, 18 GUI testų praleista. Prieš pakeitimus
  praėjo visi 77 tuomet paleidžiami testai. Papildomos patikros apima stulpelių
  poslinkį dėl piktogramų, pažymėjimo paspaudimo ribas, Unicode / plėtinius,
  tūkstančių eilučių bendrą vaizdų podėlį ir prisitaikymą prie tikro aukščio.
- GUI testuose numatyta vienoda skilčių lentelės erdvė abiem temomis / kalbomis,
  mažiausiai 5 eilučių aukštis įprastuose bandomuose languose, ilgo aprašymo
  stabilumas ir pelės pasirinkimas abiejose lentelėse. Šie testai čia NEPALEISTI:
  Xvfb negali sukurti vietinių socket. Apribojimas neapeitas.
- Tikras Windows EXE paleidimas, Windows DPI ir grafinis išdėstymas šiame
  kompiuteryje nepatikrinti. Regresiniai testai nėra visų platformų garantija.
- file_ops.py ir path_utils.py baitai sutampa su 2.4.4: kopijavimo, atkūrimo,
  valymo, Read-only, išimčių, ilgų kelių ir dalinių klaidų logika nepakeista.
- Pakavimo scenarijai įtraukia naują file_icons.py. Naudojami pagal ankstesnio
  paketo manifestą patikrinti vykdymo komponentai ir EXE paleidiklis.

## Versija 2.4.4 – 2026-10-20

- Pašalinta 2.4.3 paleidimo klaida: įvykių žyma, sudaryta kaip Tk lango kelias
  su neegzistuojančiu .ColumnWidths vaiku, pakeista klasės žyma su ne-taško prefiksu.
- Testų paviršius dabar pateikia tikrą Tk tipo lango vardą ir tikrina Tk bind
  reikalavimą tašku prasidedančioms žymoms. Su 2.4.3 kodu visi keturi valdiklio
  testai atkuria bad window path name klaidą; su pataisa jie praeina.
- Linux praėjo 77 testai; 16 tikro GUI testų vis dar praleista. Tikras EXE
  paleidimas Windows aplinkoje šioje darbo aplinkoje neatliktas.
- Naudojami patikrinti ankstesnio paketo vykdymo komponentai. Keičiamas programos
  kodas ir diagnostiniai testai, išlieka ankstesnių pataisų funkcijos.

## Versija 2.4.3 – 2026-10-20

- Abiejų failų lentelių stulpeliams išjungtas automatinis tempimas; skirtukų
  tempimas apdorojamas prieš Tk Treeview klasės pločio perskirstymo įvykius.
- Pradinis kelio plotis pritaikomas prie lango. Po rankinio pakeitimo kitų
  stulpelių pločiai nekeičiami, pasirinkimai išlieka tos sesijos metu. Išsaugoma
  ir horizontalios slinkties vieta per sąrašo perpiešimą.
- Linux praėjo 77 testai; 16 GUI testų praleista dėl grafinės aplinkos ribojimų.
  Keturi valdiklio testai naudoja imituotą stulpelių / įvykių paviršių: jie tikrina
  pločių nepriklausomumą, ribas, atkūrimą ir vietinių tempimo įvykių blokavimą.
- Pridėtas tikro GUI testas generuoja pelės tempimą abiejose lentelėse ir tikrina
  slinktį, perpiešimą bei išplėsto lango atidarymą iš naujo. Jis šiame paleidime
  praleistas; patikra tikrame Windows lieka būtina.
- Naudojami pagal manifestą patikrinti ankstesnio 2.4.2 paketo vykdymo komponentai.

## Versija 2.4.2 – 2026-10-20

- Šoninio meniu mygtukai išlaiko įprastas fono / teksto / rėmelio spalvas,
  kai navigacija užblokuota. Bendras neaktyvių veiksmų mygtukų stilius išlieka.
- Atnaujintas esamas abiejų temų GUI būsenų testas: navigacijos spalvų išlaikymas,
  paspaudimo blokavimas ir spalvos grįžus į įprastą būseną.
- Linux praėjo 73 testai, 15 GUI testų praleista dėl grafinės aplinkos ribojimų.
  Šio vaizdo pakeitimas tikroje Windows aplinkoje dar netikrintas.
- Paketui naudojami pagal manifestą patikrinti 2.4.1 vykdymo komponentai.

## Versija 2.4.1 – 2026-10-20

- Linux praėjo 73 testai. 15 GUI testų praleista; tikras Windows vykdymas netikrintas.
- Patikrinti vietiniai ir UNC keliai, Python OSError pateikiami užkoduoti keliai,
  abu pervadinimo klaidos keliai, Unicode / apostrofai ir pakartotinis formatavimas.
- Tikrinti pradinių reikšmių, programinio įvedimo ir Tcl tiesioginio įklijavimo
  kelio laukeliai be grafinio ekrano. Tai nepakeičia tikro grafinio GUI bandymo.
- Patikrintas senos istorijos atvaizdavimas LT ir EN, eksportuojamos kopijos
  formatavimas, nauji skaitymo ir vykdymo klaidų žurnalai. Darbiniai keliai
  ir seni istorijos failai nekeičiami atvaizdavimo funkcijų.
- Vykdymo komponentai ir EXE paleidiklis pernaudojami patikrinus ankstesnio
  2.4.0 paketo kontrolines sumas. Programos versija rodoma kaip 2.4.1.

## Versija 2.4.0 – 2026-10-14

- Linux: 65 failų operacijų / kelių testai; 15 GUI testų praleista.
  Xvfb atsisiųstas į vietinį laikiną aplanką, tačiau šioje aplinkoje vietinių
  socket sukūrimas grąžina EPERM. Apribojimas neapeitas; tikras GUI netikrintas.
- 350 failų scenarijuje 347 nukopijuoti, 3 imituotai užblokuoti failai išliko
  matomi ir žurnale. Patikrintas atkūrimas bei dalinis valymas, nežinomo tipo
  įrašas, šakninio nuskaitymo blokavimas ir nesusietų klaidų fail-closed elgsena.
- Neperskaitytos šakos, tėvinių katalogų ir gretimų panašiai pavadintų šakų
  atskyrimas patikrintas. Pakeitus GUI eilutės būseną, variklio apsauga išlieka.
- Windows atributai ir klaidos simuliuoti: Read-only pašalinamas tik po
  patikrinto archyvavimo; kiti bitai išsaugomi, po nesėkmės / atšaukimo
  atributas grąžinamas. Antivirusinės klaida nesukelia atributų keitimo.
- Pridėti tikrų Tk valdiklių testai išimčių filtravimui / slinkimui / šalinimui,
  klaidų kopijavimui ir dalinio nuskaitymo veiksmų būsenoms. Reikia grafinio ekrano.
- Windows paketas naudoja patikrintą ankstesnį paleidiklį ir vykdymo komponentus.
  Programos versija 2.4.0; paleidiklio Properties versija gali likti 2.2.0.
- Tikras Windows / NTFS / antivirusinės vykdymas šiame kompiuteryje netikrintas.

## Versija 2.3.0 – 2026-10-14

- Linux praėjo 48 failų operacijų ir kelių testai. 12 GUI testų praleista,
  nes nėra ekrano; išdėstymas šiame leidime nekeistas.
- Patikrintas `[EP]` pažodinis išskyrimas visuose trijuose režimuose;
  Unicode, skyryba, tašku prasidedantys ir tarpus turintys pavadinimai.
- Patikrintas kopijavimas, atkūrimas, perrašymo archyvas ir valymas su ilgu
  (>260 simbolių) keliu; 96 failų lygiagretus archyvavimas į bendrus katalogus.
- Naudojant standartinės bibliotekos Windows kelių algoritmą ir simuliuojant
  pasikeitusius sistemos atsakymus, atkurtas nevienodas techninio prefikso
  pašalinimas ir senojo containment tikrinimo klaida. Tai nėra bandymas vartotojo PC.
- Išliko kelio išėjimo, nuorodų, pasikeitusių failų ir nearchyvuoto turinio apsaugos.
  Patikrinta, kad archyvo paruošimo klaida nepakeičia kopijos turinio.
- Paketas perrenkamas iš ankstesnio 2.2.0 paketo, patikrinus visų jo failų sumas.
  EXE ir vykdymo komponentai nekeisti; įkeliamas atnaujintas Python programos kodas.
- Tikras Windows / NTFS, tinklo disko ir OneDrive vykdymas čia neatliktas.

## Versija 2.2.0 – 2026-09-26

- Praėjo 49 testai: 37 failų operacijų ir 12 tikros Tkinter sąsajos testų.
- Patikrintos aiškios tamsios temos rodyklių spalvos ir išplėsto sąrašo
  bendri filtrai, žymos, rikiavimas, uždarymas bei blokavimas operacijos metu.
- Išbandytas 2000 failų sąrašas: slinkimas veikia, langas savaime nedidėja.
- Ilgas aprašymas nekeičia lentelės aukščio visuose trijuose darbo režimuose,
  tiek 1100 × 760, tiek 1440 × 980 dydžio lange.
- Katalogų šalinimo logika šiame leidime nekeista.
- Testai praėjo Linux su Tk 8.6 ir Tk 9.0; sąsaja peržiūrėta abiejose temose.
- Vietinio pradinio Python ZIP kontrolinė suma neatitiko kūrimo scenarijaus,
  todėl šis archyvas nenaudotas. Naudoti 2.1.2 pristatyto paketo komponentai,
  prieš tai patikrinus visas 1001 failo sumas. Paleidiklis sukompiliuotas iš naujo.
- Windows EXE paleidimas ir jo vaizdas tikrame Windows šiame kompiuteryje netikrinti.

## Versija 2.1.2 – 2026-09-25

- Praėjo visi 45 testai: 37 failų operacijų ir 8 tikros Tkinter sąsajos testai.
- Patikrinti katalogo šalinimo pakartojimai po imituoto Windows `WinError 5`,
  bandymų riba, stabdymas per pauzę ir apsauga nuo per pauzę pasikeitusių
  katalogų, dingusio šaltinio bei naujų failų.
- Patikrintas neaktyvių mygtukų teksto kontrastas (bent 4,5:1), neveikiantis
  paspaudimas ir spalvų atkūrimas vėl aktyvavus mygtukus abiejose temose.
- Testai praėjo Linux su Python 3.12 ir Tk 9.0 bei Tk 8.6.
- Sąsaja papildomai peržiūrėta šviesioje ir tamsioje aplinkoje, įskaitant
  1100 × 760 langą bei operacijos metu neaktyvius mygtukus.
- Windows EXE perkompiliuotas; ZIP patikra ir 1001 failo SHA-256 sumos teisingos.
- Pakete esantis programos kodas, testai ir instrukcijos sutampa su patikrintais
  šaltiniais. Programos kodo sintaksė suderinama su Python 3.10+.

Tikro Windows / OneDrive katalogo šalinimo pakartojimai šiame kompiuteryje
neišbandyti. Nuolatinio prieigos draudimo pakartojimai nepašalina.

## Pradinio paketo patikra – 2026-09-13

Patikrinta Linux aplinkoje.

- Sukompiliuotas AMD64 PE32+ EXE, Windows GUI posistemė (be terminalo lango).
- Kompiliavimas su `-Wall -Wextra -Werror`; klaidų ar įspėjimų neliko.
- Patikrinti manifesto `asInvoker` ir `longPathAware` įrašai.
- Visi 39 paketo EXE / DLL / PYD failai yra x64 architektūros.
- Patikrintos 2873 importuojamos pridėtų bibliotekų funkcijos; trūkstamų nerasta.
- Nepridėtos DLL priklausomybės priklauso Windows sistemos komponentams.
- Dviejų oficialių `libtommath.dll` kopijų vykdomasis kodas ir eksportų sąrašai sutampa.
- ZIP CRC ir visų 1000 failų sąrašas teisingi.
- Patikrintos 999 failų SHA-256 sumos paketo manifeste (pats manifestas neįtraukiamas).
- Pradiniai du Python.org atsisiuntimai patikrinti pagal kūrimo skripte įtvirtintas SHA-256 sumas.
- Python šaltinio kodo sintaksė suderinama su 3.10+.
- Pakartotinai praėjo visi 33 programos testai: 29 failų operacijų ir 4 tikro GUI testai.
  Jie vykdyti Linux su Python 3.12 ir vietiniu Tkinter, naudojant laikinus failus bei virtualų ekraną.

## Neatlikta

Tikras `BackUpStudio.exe` paleidimas Windows aplinkoje neatliktas. Statinė patikra
nepakeičia tokio bandymo ir negarantuoja veikimo konkrečioje Windows konfigūracijoje.
Windows kompiuteryje galima paleisti `BackUpStudio.exe --self-test` su pridėtu
vykdymo komponentų rinkiniu. Python atskirai nereikia. Testai naudoja savo laikinus
failus; Windows sistemoje simbolinių nuorodų testas praleidžiamas dėl teisių skirtumų.

EXE nėra pasirašytas leidėjo sertifikatu. Antivirusinės ar organizacijos politikos
vertinimas nebuvo atliktas. Apsaugos apėjimo priemonių pakete nėra.
