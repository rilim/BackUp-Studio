# BackUp Studio 2.6.0

Darbalaukio programa failų kopijavimui, palyginimui, atkūrimui ir kopijos valymui.
Sukurta pateiktos Python programos pagrindu, su lietuviška ir angliška grafine sąsaja ir
peržiūrėta failų operacijų logika.

## Kas pasikeitė 2.6.0

- „Tikrinti skirtumus“ pakartotinai naudoja atskirai šaltiniui ir kopijai išsaugotas
  SHA-256 sumas, jei nesikeitė failo tapatybė, dydis ir laiko žymos. Net kai
  suma paimama iš indekso, failą bandoma atverti ir perskaityti pirmą baitą:
  neprieinamas failas rodomas kaip skaitymo problema. Nauji ir pasikeitę failai
  perskaitomi pilnai; rezultatas rodo panaudotų ir perskaitytų sumų skaičių.
- „Pilna patikra“ perskaito visų failų turinį ir atnaujina indeksą. Naudokite ją
  periodiškai arba įtarę, kad turinys pakito nepasikeitus failo metaduomenims.
  Greita patikra tokių pokyčių gali nepastebėti. Pirmas skenavimas irgi skaito
  visus failus, kad sudarytų indeksą. Nepasiekiamas indeksas netrukdo skenuoti.
- Nutraukus tikrinimą tas pats mygtukas siūlo „Tikrinti iš naujo“; naujas
  skenavimas prasideda nuo pradžių.
- Visose failų lentelėse žymimojo langelio ir tipo piktogramos turinys
  atitrauktas 12 pikselių nuo vidinio krašto; pati lentelė neperkelta.

## Kas pasikeitė 2.5.0

- Sinchronizavimas, atkūrimas ir kopijos valymas naudoja vienodą sąrašo išdėstymą.
  Atkūrimo pasirinkimai ir valymo paaiškinimas perkelti į aplankų skydelį;
  statistikos kortelės žemesnės, todėl daugiau vietos lieka failams.
- Kompaktiškas vaizdas parenkamas ir pagal tikrą lentelei likusį aukštį.
  Sąrašas užima likusią lango vietą, o jo turinys slenka: tūkstančiai failų
  nedidina paties lango. „Išplėsti sąrašą“ atidaro atskirą didinamą langą.
- Abiejose lentelėse rodomos įtrauktos failų tipų piktogramos: aplankai, PDF,
  dokumentai, lentelės, pateiktys, tekstas, vaizdai, garsas, vaizdo įrašai,
  archyvai, kodas, programos ir bendri failai. Tipas parenkamas pagal plėtinį,
  neatidarant failo; nežinomo tipo neperskaitytiems objektams rodoma bendra piktograma.
- Žymimasis langelis lieka kairėje, o failo piktograma – šalia pavadinimo.
  Spustelėjus piktogramą ar pavadinimą pasirenkama eilutė informacijai;
  žymimasis langelis ir tarpo klavišas keičia veiksmui pažymėtus elementus.
  Dvigubas spustelėjimas veikia kaip anksčiau. Ilgas aprašymas lentelės nesumažina.
- Išlieka LT/EN, abi temos, išimtys, filtrai, eksportas, horizontalus slinkimas
  ir nepriklausomas stulpelių pločio keitimas. Failų operacijų kodas nepakeistas.

## Ankstesni 2.4.4 pakeitimai

Pašalinta 2.4.3 paleidimą blokuojanti lentelės įvykių registravimo klaida.
Tk žymas, prasidedančias tašku, laiko langų vardais; stulpelių valdiklio
žyma pakeista tinkamu unikaliu klasės pavadinimu. Stulpelių pločio pataisa išlieka.

## Ankstesni 2.4.3 pakeitimai

Abiejose failų lentelėse tempiant stulpelio ribą keičiamas tik to stulpelio plotis.
Kiti stulpeliai išlaiko savo pločius ir pasislenka į dešinę. Platesnę lentelę galima
slinkti horizontaliai. Rankiniu būdu pasirinkti pločiai ir slinkties vieta išlieka
atnaujinant, filtruojant, rikiuojant bei pažymint eilutes.

Pagrindinė ir išplėsta lentelė turi atskirai įsimenamus pločius: jie išlieka
perjungiant darbo skiltis, temą / kalbą ar uždarius ir vėl atidarius išplėstą
sąrašą toje pačioje programos sesijoje. Paleidus programą iš naujo naudojami
pradiniai pločiai. Pradinis failo kelio stulpelis prisitaiko prie lango, kol
pirmą kartą rankiniu būdu pakeičiamas bet kurio stulpelio plotis.

## Ankstesni 2.4.2 pakeitimai

Skenuojant ir vykdant failų operacijas šoninio meniu punktų fono, teksto ir
rėmelio spalvos nekeičiamos. Pasirinktas punktas išlieka paryškintas; kiti
punktai išlieka įprastos spalvos. Navigacija tuo metu vis tiek užblokuota.
Tai galioja abiem temoms. Kitų neaktyvių mygtukų stilius išlieka toks pats.

## Ankstesni 2.4.1 pakeitimai

Keliai sąsajoje rodomi be techninio `\\?\` prefikso. Tai taikoma šaltinio,
kopijos, versijų ir išimčių laukeliams, progresui, patvirtinimams, klaidoms,
istorijai, klaidų kopijavimui bei žurnalo eksportui. Tinklo keliai pateikiami
įprastu `\\serveris\aplankas` formatu. Windows klaidos tekste esantys papildomai
užkoduoti keliai taip pat perskaitomai atvaizduojami. Seni istorijos failai
neperrašomi – pataisomas jų vaizdas ir eksportuojama kopija.

Vidinis ilgų kelių formatas, kopijavimo, archyvavimo ir trynimo logika išlieka.

## Ankstesni 2.4.0 pakeitimai

- Pavienės nuskaitymo klaidos nebeblokuoja kitų, patikimai perskaitytų failų
  kopijavimo, atkūrimo ar valymo. Neperskaityti objektai rodomi kaip apsaugoti;
  juos galima rasti filtru „Skaitymo problemos“. Visa klaida matoma failo informacijoje.
- Neperskaityto katalogo šaka ir jos tėviniai katalogai apsaugomi nuo veiksmų.
  Galima tvarkyti perskaitytus gretimus failus. Darbo šakninio katalogo klaida
  arba jo pasikeitimas vis dar sustabdo visą operaciją.
- Po sėkmingo archyvavimo Windows valymas gali nuimti failo „Read-only“ atributą
  ir pakartoti trynimą. ACL teisės ir kiti atributai nekeičiami. Jei tas pats failas
  lieka po nesėkmės ar sustabdymo, „Read-only“ grąžinamas.
- Problemų lange yra slinkties juosta, klaidų skaičius ir „Kopijuoti klaidas“.
  Išimčių lange – paieška, abi slinkties juostos ir bendras / rodomas / pažymėtas skaičius.
- Windows automatiškai praleidžiami viršutinio darbo aplanko lygio
  `System Volume Information` ir `$RECYCLE.BIN` abiejose pusėse. Tai nurodyta išimčių lange.
- Istorijoje atskirai saugomi nuskaitymo metu apsaugoti įrašai ir vykdymo klaidos.
  Neperskaityto katalogo nežinomų vaikų skaičius nespėjamas. Antivirusinės apsauga neapeinama.

Jei kopijos vieta yra visas diskas (pvz., `U:\`), archyvavimui nustatymuose
nurodykite atskirą versijų aplanką už abiejų darbo diskų ribų. Vien tik tuštiems
katalogams pašalinti archyvo nereikia.

## Ankstesni 2.3.0 pakeitimai

- Išimtys priima pažodinius katalogų pavadinimus, įskaitant `2010 - Yes [EP]`,
  lietuviškas raides, apostrofus ir kitus failų sistemos leidžiamus simbolius.
  Skliaustai nėra paieškos šablonas. Pavadinimai nepervadinami.
- Windows failų operacijos nuosekliai naudoja ilgus kelius palaikantį formatą.
  Pataisytas archyvo kelio tikrinimas, kuris galėjo atmesti to paties kelio
  variantus su techniniu prefiksu ir be jo.
- Archyvo katalogai paruošiami prieš lygiagrečias failų užduotis. Failų turinys
  tikrinamas, o failai iš kopijos šalinami tik sėkmingai išsaugojus juos archyve.
- Tikrai tuščiam katalogui gavus laikiną „aplankas netuščias“ klaidą, bandymas
  pakartojamas pagal nustatytą bandymų skaičių. Atsiradęs turinys išsaugomas.
- Klaidoje nurodomas etapas ir kelias; žurnale išsaugomi ir sistemos klaidų kodai.
  Jei liko nearchyvuotų failų, istorija paaiškina, kodėl katalogas paliktas.

Atnaujinimas: išskleiskite visą naują ZIP į atskirą aplanką. Paleidus sąsajos
apačioje turi būti **2.6.0**. Esami nustatymai ir kopijos išlieka. Paketas naudoja
patikrintą ankstesnį EXE paleidiklį, todėl jo „Properties“ versija gali būti 2.2.0;
tikrą programos versiją rodo pati sąsaja.

## Paleidimas „Windows“

### Paruoštas EXE paketas – be Python diegimo

1. Atsisiųskite **BackUp_Studio_Windows_x64.zip** ir išskleiskite visą ZIP.
2. Išskleistame `BackUpStudio` aplanke atidarykite **BackUpStudio.exe**.
3. Demonstracijai naudokite **Demonstracija.bat**.

Paketas skirtas Windows 10 / 11 x64. Python ir Tcl/Tk jau pridėti;
papildomo diegimo, administratoriaus teisių ar interneto paleidimui nereikia.
`_internal` aplankas turi likti šalia EXE – perkelkite visą programos aplanką
arba sukurkite EXE nuorodą. Nustatymai saugomi kaip ir Python versijoje.

EXE nėra pasirašytas leidėjo sertifikatu. Paketas sukompiliuotas ir statiškai
patikrintas Linux aplinkoje; tikras paleidimas Windows dar nepatikrintas.
Jei atsirastų paleidimo klaida, žiūrėkite `%LOCALAPPDATA%/BackUpStudio/startup.log`.
Išsamesnė paketo informacija yra `SKAITYTI.txt`.

### Paleidimas iš Python šaltinio kodo

1. Išskleiskite visą ZIP į atskirą aplanką. Nepaleiskite failų tiesiai iš ZIP.
2. Reikia **Python 3.10 arba naujesnio su Tcl/Tk (tkinter)**. Papildomų Python
   paketų diegti nereikia. Standartiniame Python diegiklyje palikite įjungtą Tcl/Tk.
3. Atidarykite **Start_BackUp.bat**. Atsidarys programos langas.
4. Demonstracijai naudokite **Start_Demo.bat**. Ji sukuria tik laikinus pavyzdinius
   failus, naudoja atskirus nustatymus ir po uždarymo juos pašalina.

Alternatyva komandinėje eilutėje, programos aplanke:

```text
py -3 main.py
py -3 main.py --demo
```

Jei paleidimo langas neatsidaro, paleiskite `py -3 main.py` terminale – taip
matysite klaidos tekstą. Linux / macOS sistemoje naudokite `python3 main.py`;
reikalingas tkinter ir grafinė aplinka. Šis būdas skirtas šaltinio kodo paketui;
paruoštame Windows EXE pakete šių veiksmų nereikia.

## Įprastas naudojimas

Kalbą (**Lietuvių / English**) ir aplinką (**Šviesi / Tamsi**) pasirinkite
**Nustatymai → Kalba ir išvaizda**, tuomet spauskite **Išsaugoti nustatymus**.
Sąsaja persijungia iškart; pasirinkimai išlieka po programos uždarymo.
Keičiant juos po skirtumų patikros pažymėti failai išlieka pažymėti.
Kalbos ir aplinkos pasirinkimas nekeičia kopijuojamų failų turinio.
Nustatymų turinį galima slinkti; išsaugojimo mygtukas lieka matomas lango apačioje.
Neaktyvūs mygtukai abiejose aplinkose turi neutralų foną, įskaitomą tekstą ir
subtilų rėmelį. Jie nereaguoja į paspaudimą, o pelės žymeklis lieka įprastas.
Aktyvūs pagrindiniai veiksmai išskiriami turkio spalva.

1. Kairėje pasirinkite **Sinchronizavimas**, **Atkūrimas** arba **Kopijos valymas**.
2. Nurodykite **Šaltinį** ir **Atsarginę kopiją**: kelią įrašykite arba rinkitės
   mygtuku „…“. Galima nurodyti ir tinklo aplanką, kurį pasiekia jūsų vartotojas.
3. Atidarykite **Tvarkyti išimtis**. Pasirinkite nekopijuojamus šaltinio
   poaplankius arba įveskite jų santykinius kelius, pvz., `Dokumentai/Laikina`.
4. Spauskite **Tikrinti skirtumus** (arba F5). Tikrinamas abiejų pusių failų turinys.
   Palyginimas pats nekopijuoja, netrina ir nekuria paskirties aplanko.
5. Filtruokite, ieškokite, pažymėkite norimas eilutes. Stulpelis **Pažymėjus**
   paaiškina, koks veiksmas bus atliekamas. Suvestinės korteles galima paspausti.
6. Spauskite veiksmų mygtuką apačioje ir patvirtinkite konkretų pasirinkimą.
   Po operacijos skirtumai automatiškai tikrinami iš naujo.

Kopijavimas ir turinio patikra vyksta foninėse gijose. Veiksmą galima stabdyti.
Jau užbaigti pakeitimai išlieka; nebaigti laikini kopijavimo failai pašalinami.
Stabdymas gali užtrukti, kol operacinė sistema grąžins valdymą iš failo operacijos,
ypač nepasiekiamame tinklo diske. Uždarant veikiančią programą siūloma pirmiausia
saugiai sustabdyti operaciją.

## Būsenos ir pasirinkimas

| Būsena | Reikšmė ir galimi veiksmai |
| --- | --- |
| Naujas šaltinyje | Yra tik šaltinyje; galima nukopijuoti į kopiją. |
| Pakeistas | Failų turinys skiriasi; galima perrašyti pasirinkta kryptimi. |
| Kopija naujesnė | Turinys skiriasi, kopijos data naujesnė. Sinchronizuojant automatiškai nepažymima; galite pasirinkti ranka. |
| Tik kopijoje | Galima atkurti į šaltinį arba archyvuoti valymo režimu. |
| Vienodas | Turinys sutampa; kopijuoti nereikia, net jei datos skirtingos. |
| Tipo konfliktas | Vienoje pusėje failas, kitoje aplankas; elementas ir jo palikuonys nevykdomi. Konfliktą sutvarkykite failų naršyklėje. |

Kortelėse skaičiuojami failai. Lentelėje ir pasirinkimo suvestinėje gali būti
ir tušti / trūkstami aplankai. Bendri, vienodi aplankai lentelėje nerodomi.

- Paspaudus langelį pirmame stulpelyje pažymimas failas. Veikia ir dvigubas
  paspaudimas eilutėje arba tarpas klaviatūroje.
- Pažymėjus aplanką pažymimi ir jo tinkami palikuonys, įskaitant tuo metu
  paieškos ar filtro paslėptus. Apatinė suvestinė rodo **visą** pasirinkimą.
- **Pažymėti rodomus** prideda tik šiuo metu matomas tinkamas eilutes.
- **Nuimti žymas** išvalo visą pasirinkimą. Filtras **Pažymėti** parodo visus
  pasirinktus elementus (paieškos laukas ir tuomet taikomas).
- Antraštės rikiuoja lentelę; Ctrl+F perkelia žymeklį į paiešką.
- Dešiniuoju pelės mygtuku galima atverti atitinkamą šaltinio ar kopijos aplanką.
  „Failo informacija“ arba Enter parodo dydžius, datas ir numatomą veiksmą.
- Žemesniame lange sąsaja automatiškai tampa kompaktiškesnė, kad liktų vietos lentelei.
- **Išplėsti sąrašą** atveria atskirą keičiamo dydžio langą, kurį galima išdidinti
  iki viso ekrano. Paieška, filtrai, rikiavimas ir žymos bendri abiem langams.
  Uždarius langą pasirinkimas išlieka; naujo skenavimo nereikia. Keičiant darbo
  skiltį išplėstas langas uždaromas. Enter arba **Failo informacija** atveria informaciją.
- Informacijos juosta išlieka po pagrindiniu sąrašu ir nekeičia aukščio pasirinkus
  failą. Ilgą tekstą galima slinkti pačioje juostoje. Abu sąrašai slenkami ir
  nedidėja automatiškai pagal failų skaičių.
- Tamsios aplinkos nustatymų rodyklės yra šviesios, didesnės ir paryškėja užvedus pelę.
- **Eksportuoti CSV** išsaugo šiuo metu rodomas eilutes, jų būsenas ir žymas.
  Naudojamas UTF-8 su BOM ir kabliataškiai, tinkami atidaryti „Excel“.

## Atkūrimas

**Tik trūkstamus** – atkuria tik šaltinyje nesančius failus ir aplankus.
Egzistuojantys, besiskiriantys failai šiame režime neperrašomi.

**Ir perrašyti esamus** – leidžia pažymėti ir besiskiriančius failus. Kopijuojama
iš atsarginės kopijos į šaltinį. Ankstesnės šaltinio versijos išsaugomos, jei
nustatymuose įjungtas jų saugojimas (pradinis pasirinkimas – įjungtas).

Jei šaltinio aplanko nėra, jį galima įrašyti ranka ir sukurti atkuriant.
Sinchronizavimas ir valymas be pasiekiamo šaltinio blokuojami.

## Išimtys

Pradinės išimtys perkeltos iš senosios konfigūracijos:
`Investavimas` ir `Islaidos/Islaidos UK`.

Išimtis apima konkretų santykinį aplanko kelią ir jo palikuonis. Pavyzdžiui,
`Investavimas` nepraleidžia aplanko `Investavimas_kita`.
Išimtys taikomos abiejose pusėse ir visoms operacijoms. Jos nekeičia jau esančio
neįtraukto turinio. Šablonai su `*` ar `?` nenaudojami.
Pakeitus šaltinį išimtys lieka santykinės naujajam šaltiniui – peržiūrėkite jų sąrašą.

## Versijos ir valymas

Pagal nutylėjimą prieš perrašant failą saugoma jo ankstesnė versija. Archyvas
kuriamas **šalia kopijos**, pvz., `C:/D/BackUp/Copy.versions`, atskirai nuo
abiejų darbo aplankų. Nustatymuose galite pasirinkti kitą vietą.

Kiekviena operacija turi atskirą datos ir unikalaus numerio aplanką:

- `before_sync` – failai, buvę kopijoje prieš perrašymą;
- `before_restore` – failai, buvę šaltinyje prieš atkūrimą;
- `deleted_from_backup` – iš kopijos pašalinti failai;
- `manifest.json` – operacijos aprašymas ir rezultatai.

**Kopijos valymas** nėra automatiškai vykdomas po sinchronizavimo. Jis atliekamas
atskirai ir tik pažymėtiems elementams. Failas pašalinamas iš kopijos tik
sėkmingai išsaugojus ir patikrinus jo archyvo kopiją. Aplankas pašalinamas tik
jei tuščias; nepažymėti ir neįtraukti jo failai išlieka.

Laikinai nepavykęs tuščio katalogo šalinimas kartojamas pagal **Nustatymai →
Bandymų skaičius** (įskaitomas pirmasis bandymas). Pradinė reikšmė – 3 bandymai,
tarp jų laukiama 1 ir 2 sekundes. Kiekvieną kartą iš naujo tikrinami darbo
aplankai, šalinamo katalogo tapatybė ir ar jo vis dar nėra šaltinyje. Naujas ar
nepažymėtas turinys nešalinamas. Laukimą galima nutraukti mygtuku **Stabdyti**.
Nuolatinis prieigos draudimas išlieka klaida; ACL teisės automatiškai nekeičiamos.
Vienintelė atributų išimtis – aukščiau aprašytas jau archyvuoto failo „Read-only“ šalinimas.

Istorijoje pasirinkite operaciją ir spauskite **Atverti operacijos versijas**.
Ankstesnę versiją galima pasiimti failų naršyklėje arba pasirinkti atitinkamą
`before_sync`, `before_restore` ar `deleted_from_backup` poaplankį kaip kopijos
šaltinį atkūrimo režime. Pasirinkite patį turinio poaplankį, ne katalogą su
`manifest.json`. Grąžinant įprastą darbą atstatykite ankstesnį kopijos kelią.

Archyvo versijos šioje versijoje automatiškai nevalomos; jų vietą reikia prižiūrėti.
Žurnaluose esantys absoliutūs failų keliai matomi tam kompiuterio vartotojui.

## Patikimumas ir ribos

- Nauji ir pakeisti failai tikrinami pagal turinį (SHA-256). Greitas skenavimas
  naudoja atskirą šaltinio ir kopijos sumų indeksą programos duomenų aplanke;
  jis nepaslepia pasikeitusios tapatybės, dydžio ar laiko žymų. Pilna patikra
  visada perskaito turinį. Senasis bendras `hash_index.json` nenaudojamas.
- Pasirinkti failai tikrinami pakartotinai prieš operaciją. Pasikeitus duomenims
  po palyginimo reikalaujama naujo palyginimo arba konkreti operacija pažymima klaida.
- Kopijuojama į laikiną failą paskirties aplanke; patikrinus turinį atliekamas
  galutinio failo pakeitimas. Kopijavimo klaida nelaikoma sėkme.
- Jei nepavyksta išsaugoti privalomos ankstesnės versijos, senas failas neperrašomas.
- Pavienės skaitymo klaidos apsaugo konkrečius kelius; kitiems patikrintiems
  objektams veiksmai leidžiami. Šakninio katalogo klaida blokuoja visą vykdymą.
- Simbolinės nuorodos, „junction“ ir kiti „reparse point“ elementai sąmoningai
  neapdorojami. Tai gali apimti kai kuriuos debesijos failų vietaženklius.
  Atsisiųskite reikiamus failus lokaliai arba pridėkite netinkamus aplankus prie išimčių.
- Tai failų turinio ir įprastų datų kopijavimo įrankis. Jis nesukuria disko atvaizdo,
  VSS momentinių kopijų, neužtikrina veikiančios duomenų bazės nuoseklumo ir
  neperkelia visų NTFS teisių / papildomų srautų. Atvirus, nuolat keičiamus
  failus prieš kopijavimą rekomenduojama uždaryti.
- Viena operacija apdoroja vieną aplankų porą. Sinchronizuojama viena pasirinkta
  kryptimi; automatinio abipusio konfliktų sprendimo ir darbo pagal tvarkaraštį nėra.
- Turinio patikra reiškia, kad kiekvienam palyginimui failai perskaitomi.
  Progreso ir likusio laiko reikšmės yra apytikslės, ypač archyvuojant didelius failus.
- Laisva vieta tikrinama pasirinktiems failams, laikinoms kopijoms ir archyvui,
  konservatyviai sumuojant jų dydžius. Naujas labai didelis failas darbalaukio
  diske ar kitos programos rašymas gali pakeisti laisvą vietą jau vykstant operacijai.
- Kopija tame pačiame fiziniame diske neapsaugo nuo to disko gedimo.

## Failai ir nustatymai

Šeši pagrindiniai moduliai pakeičia ankstesnę programos versiją kaip vienas
suderintas rinkinys. Nemaišykite senų ir naujų modulių.

| Failas | Paskirtis |
| --- | --- |
| `main.py` | Paleidimas ir demonstracija. |
| `ui.py` | Tkinter sąsaja ir foninių užduočių valdymas. |
| `file_ops.py` | Nuskaitymas, palyginimas, kopijavimas, archyvavimas, atkūrimas. |
| `config.py` | Nustatymų modelis ir atominis JSON įrašymas. |
| `utils.py` | Keliai, išimtys, formatavimas, CSV eksportas. |
| `i18n.py` | Lietuviški ir angliški sąsajos tekstai. |

Nustatymai ir operacijų žurnalai saugomi vartotojo duomenų aplanke:

- Windows: `%LOCALAPPDATA%/BackUpStudio`;
- Linux: `$XDG_STATE_HOME/BackUpStudio` arba `~/.local/state/BackUpStudio`;
- demonstracijoje: atskirame laikiname aplanke.

## Patikra

Automatizuoti testai kuria ir pašalina tik savo laikinus bandomuosius failus:

```text
py -3 -m unittest discover -s tests -v
```

Šiame leidime Linux aplinkoje praėjo 83 testai: 65 failų operacijų / kelių,
8 kelių atvaizdavimo (įskaitant Tcl laukelius be grafinio ekrano), 6 stulpelių /
išdėstymo valdymo ir 4 piktogramų / pažymėjimo testai be grafinio ekrano.
Dar 18 Tkinter sąsajos testų šiame paleidime praleista: virtualaus ekrano
paleidimą riboja aplinkos leidimai. Testai naudoja laikinus
failus. Failų operacijų testai apima palyginimą, išimtis, abu atkūrimo režimus, pasirinktų
failų vykdymą, saugų valymą, versijas, klaidas, disko vietą, pasikeitusį turinį ir
stabdymą. GUI testams reikia grafinės aplinkos ir tkinter; be jos jie praleidžiami.
Įtraukti katalogų šalinimo pakartojimų, per pauzę pasikeitusių aplankų ir naujų
failų apsaugos, neaktyvių mygtukų kontrasto bei būsenų persijungimo testai.
GUI patikros papildytos trijų skilčių vienodo aukščio, piktogramų ir pelės
paspaudimų abiejose lentelėse scenarijais. Šios grafinės patikros čia neatliktos.
Ši versija patikrinta Linux aplinkoje; tikras Windows paleidimas ir Windows
specifinės failų teisės šiame etape dar nepatikrinti.
