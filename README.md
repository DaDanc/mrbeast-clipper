# Twitch clipper → TikTok (@beastgodclipgod)

Automatski uzima najgledanije Twitch klipove (Jynxzi, rezerva CaseOh), montira ih u vertikalni
video s titlovima i zakazuje na TikTok preko Buffera, 3× dnevno (14:00, 20:00, 22:00 po
zagrebačkom vremenu, svaki dan s malim nasumičnim pomakom). Sve radi na GitHub Actions –
računalo ne mora biti upaljeno.

## Kako radi

1. **Objavi Twitch klip** (workflow) se pokreće oko svakog termina:
   - Twitch Helix API → top klipovi zadnjih 7 dana po pregledima, prvo Jynxzi, pa CaseOh
   - filteri: 10–60 s, engleski, dovoljno pregleda, bez zabranjenih riječi u naslovu,
     nije već objavljen (`posted.json`)
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
| `termini`, `pomak_minuta` | vremena objava i nasumični pomak (± min) |
| `obavijest_za_svaku_objavu` | `true` = @mention i za svaku uspješnu objavu (inače samo za greške i preglede) |

**Dodati / promijeniti streamera:** kopiraj jedan blok u `streameri`, promijeni `login`, `ime` i
`hashtagovi`, ostavi `"facecam": null`. Redoslijed u popisu = prioritet.

Termini u `config.json` moraju biti unutar sati u kojima se workflow pokreće (cron u
`.github/workflows/objavi-klip.yml`, sat prije termina); za nove termine promijeni i cron.
