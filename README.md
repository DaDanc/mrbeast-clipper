# Twitch clipper → TikTok (@beastgodclipgod)

Automatski uzima najgledanije Twitch klipove (Jynxzi, rezerva CaseOh), montira ih u vertikalni
video s titlovima i zakazuje na TikTok preko Buffera, 3× dnevno u nasumična vremena
(svaki dan druga, između 12:00 i 23:30 po zagrebačkom vremenu, barem 2 h razmaka). Sve radi na GitHub Actions –
računalo ne mora biti upaljeno.

## Kako radi

1. **Objavi Twitch klip** (workflow) se pokreće svaki sat i radi samo kad je termin blizu:
   - Twitch Helix API → top klipovi zadnjih 7 dana po pregledima, prvo Jynxzi, pa CaseOh
   - filteri: 10–60 s, engleski, dovoljno pregleda, bez zabranjenih riječi u naslovu,
     nije već objavljen (`posted.json`)
   - **vrhunac**: po zvuku nađe najglasniji trenutak (vrisak, dernjava). Ako je kasno u klipu, video
     počinje s ~2 s tog trenutka (teaser), pa ide klip od najviše 6 s prije vrhunca – dosadan početak se reže
   - skidanje (yt-dlp, rezerva direktni Twitch link), titlovi riječ po riječ (faster-whisper),
     hook iz naslova klipa na vrhu prve ~3 s
   - video na Cloudinary → Buffer ga zakaže za termin → ID klipa se upiše u `posted.json`
2. **Obavijesti** (svaka 4 sata): kad Buffer objavi klip, u pinani Issue
   **📋 Objave na TikToku** stiže 🔔 s linkom; 🚀 kad TikTok prijeđe 500 / 1.000 / 5.000 pregleda.
3. Ako bilo koji run padne (nema klipova, Twitch/Buffer greška, ffmpeg…) stiže ❌ obavijest
   s @mentionom i linkom na log.

## Secrets (Settings → Secrets and variables → Actions)

| Secret | Odakle |
|---|---|
| `TWITCH_CLIENT_ID` | dev.twitch.tv/console → Register Your Application |
| `TWITCH_CLIENT_SECRET` | ista aplikacija → New Secret |
| `BUFFER_API_KEY` | publish.buffer.com/settings/api |
| `CLOUDINARY_URL` | Cloudinary dashboard (`cloudinary://...`) |

Provjera: **Actions → Provjeri postavke → Run workflow** – mora završiti s ✅ SVE SPREMNO.

## Test bez objave

**Actions → Objavi Twitch klip → Run workflow** (kvačica *Test* uključena, broj videa 3).
Gotovi videi, sličice i opisi postova su na dnu stranice runa pod **Artifacts → test-videi**.
Ako isključiš *Test*, ručni run odmah zakaže pravi klip za sljedeći slobodan termin.
U polje *klipovi* možeš upisati Twitch ID-jeve klipova (iz `opisi.txt` test runa): uz uključen *Test* napravi
samo te videe (artifact), uz isključen *Test* ih objavi DANAS u nasumična vremena.

Stare objave iz Buffer reda: **Provjeri postavke** → polje *obrisi* (tekst koji objava sadrži).

## config.json

| Postavka | Značenje |
|---|---|
| `streameri` | redom: prvi je glavni, ostali su rezerva (koriste se kad glavni nema dobrih klipova) |
| `streameri[].login` | Twitch korisničko ime (iz linka twitch.tv/**login**) |
| `streameri[].ime` | ime za prikaz |
| `streameri[].min_pregleda` | klip mora imati barem toliko pregleda na Twitchu |
| `streameri[].hashtagovi` | hashtagovi u opisu posta |
| `streameri[].facecam` | `null` = varijanta A (mutna pozadina + klip u sredini); `{x, y, w, h}` = varijanta B (facecam gore, igra dolje). Brojevi su udio slike 0–1 (npr. `x: 0.5` = od sredine) |
| `dana_unazad` | koliko dana unazad se traže klipovi |
| `min_sekundi`, `max_sekundi` | dopušteno trajanje klipa |
| `jezik` | jezik klipa (`en`) |
| `blokirane_rijeci` | klip s ovom riječi u naslovu se preskače |
| `hook_sekundi`, `hook_max_rijeci` | koliko dugo i koliko riječi ima naslov na vrhu videa |
| `opis_posta` | predložak opisa: `{hook}`, `{login}`, `{ime}`, `{hashtagovi}` |
| `objave_dnevno`, `prozor_objava`, `min_razmak_minuta` | koliko objava dnevno, između kojih sati (nasumično) i najmanji razmak |
| `vrhunac` | `ukljuceno` (false = uvijek cijeli klip), `teaser_sekundi` (duljina teasera na početku), `max_uvod_sekundi` (koliko klipa ostaje prije vrhunca), `min_kontrast_db` (koliko vrhunac mora biti glasniji od ostatka), `vrhunac_nakon_sekundi` (ako je vrhunac ranije, ništa se ne reže) |
| `obavijest_za_svaku_objavu` | `true` = @mention i za svaku uspješnu objavu (inače samo za greške i preglede) |

**Dodati / promijeniti streamera:** kopiraj jedan blok u `streameri`, promijeni `login`, `ime` i
`hashtagovi`, ostavi `"facecam": null`. Redoslijed u popisu = prioritet.

