# MrBeast kliper

Automatski radi klipove iz MrBeast videa, objavljuje ih na TikTok, Instagram i YouTube Shorts preko Buffera i skuplja linkove koje predaješ na Vyro za isplatu.

Sve radi na GitHubovim serverima, tvoje računalo ne mora biti upaljeno.

## Kako to izgleda kad je postavljeno

1. Na Vyro uzmeš link na materijal MrBeast kampanje.
2. Na GitHubu pokreneš **"1. Napravi klipove"** i zalijepiš link. Program sam napravi 6 klipova s titlovima.
3. Za svaki klip dobiješ **Issue** s pregledom. Dobar klip označiš labelom **`objavi`**, loš zatvoriš.
4. Odobreni klip ide odmah na TikTok, Instagram i YouTube.
5. Unutar sat vremena linkovi objava pojave se u Issueu **📋 Linkovi za Vyro**. Predaš ih na Vyro.

Tvoj posao: oko 10 minuta po kampanji. Sve ostalo je automatsko.

---

## Postavljanje (jednom, oko 30 minuta)

### Korak 1: GitHub repozitorij

1. Na github.com klikni **+** (gore desno) → **New repository**.
2. Ime: `mrbeast-clipper`. Odaberi **Public** (dobiješ neograničeno besplatnih minuta; ključevi ostaju tajni jer su u Secrets).
3. Klikni **Create repository**.
4. Na stranici novog repoa klikni **uploading an existing file**.
5. Raspakiraj zip koji si dobio i **povuci sve iz mape** u preglednik, uključujući mapu `.github`.
   - Na Macu je `.github` skrivena: u Finderu pritisni **Cmd + Shift + .** da se pokaže.
6. Dolje klikni **Commit changes**.
7. Otvori karticu **Actions**. Moraš vidjeti 4 workflowa (0, 1, 2, 3). Ako piše da su isključeni, klikni zeleni gumb da ih uključiš.

### Korak 2: Buffer

1. Na buffer.com, u **Channels**, poveži:
   - **TikTok**
   - **Instagram**: mora biti *Professional* račun (Creator ili Business). Prebaciš ga u Instagram postavkama → Account type.
   - **YouTube**
   - Besplatni plan dopušta 3 kanala, točno koliko treba.
2. Otvori **publish.buffer.com/settings/api** → **Create key** → kopiraj ključ.
3. U GitHub repou: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
   - Name: `BUFFER_API_KEY`
   - Secret: zalijepi ključ
   - **Add secret**

### Korak 3: Cloudinary (besplatno spremište za klipove)

Buffer ne prima datoteke, nego samo link na video. Cloudinary taj link daje.

1. Registriraj se na **cloudinary.com** (besplatni plan, kartica ne treba).
2. Na **Dashboardu** nađi **API Environment variable**. Izgleda ovako:
   `CLOUDINARY_URL=cloudinary://123456:abcDEF@tvojcloud`
3. Klikni ikonu oka da vidiš cijeli tekst. Kopiraj **samo dio od `cloudinary://` nadalje**.
4. Dodaj GitHub secret kao u koraku 2:
   - Name: `CLOUDINARY_URL`
   - Secret: `cloudinary://123456:abcDEF@tvojcloud`

### Korak 4: Provjera

1. **Actions** → **0. Provjeri postavke** → **Run workflow** → zeleni **Run workflow**.
2. Pričekaj minutu, klikni na pokretanje pa na **check**.
3. Na kraju mora pisati **✅ SVE SPREMNO**. Ako ne piše, iznad piše što ne valja.

### Korak 5: Vyro

1. Registriraj se na **vyro.com** i poveži **iste** TikTok, Instagram i YouTube račune koje si povezao u Bufferu. Inače ti pregledi neće biti priznati.
2. Poveži **PayPal ili Stripe** za isplatu.
3. Pod **Active Campaigns** nađi MrBeast kampanju i klikni **Join**.
4. **Pročitaj cijeli brief.** Zadnje MrBeast kampanje tražile su:
   - hashtagove **#mrbeast #mrbeastpartner** (već su uključeni)
   - najmanje **20 sekundi** (klipovi su 25–55 s)
   - Ako brief traži nešto drugo, otvori `config.yaml` u repou, klikni olovku, promijeni i spremi.

---

## Svakodnevno korištenje

### Kad krene nova MrBeast kampanja

**Brzina je bitna:** zadnje kampanje trajale su 1–2 dana, a budžet dijele svi kliperi. Prvi klipovi dobiju najviše.

1. Na Vyro, na stranici kampanje, kopiraj link na **materijal (source content)**.
   - Ako link ne možeš kopirati, preuzmi video, stavi ga na svoj Google Drive i u dijeljenju odaberi **Anyone with the link**. Kopiraj taj link.
2. Na GitHubu: **Actions** → **1. Napravi klipove** → **Run workflow**.
3. Zalijepi link u polje → **Run workflow**.
4. Čekaj **20–40 minuta**. Može i s mobitela, preko GitHub aplikacije.

### Pregled klipova (5 min, s mobitela)

1. Otvori karticu **Issues**. Svaki klip je jedan Issue sa sličicom.
2. Klikni **▶️ Pogledaj klip**.
3. Dobar klip: desno **Labels** → označi **`objavi`**. Za minutu ide na sve tri mreže.
4. Loš klip: **Close issue**.

Savjet: objavi 2–4 najbolja, ne sve. Previše sličnih objava odjednom može smanjiti doseg računa.

### Predaja na Vyro

1. Unutar sat vremena otvori Issue **📋 Linkovi za Vyro** (zakačen je na vrhu Issuesa).
2. Za svaki link: Vyro → tvoja kampanja → **Submit Post** → zalijepi → Submit.
3. Pregledi se broje **tek od predaje**, zato predaj čim linkovi stignu.

---

## Kad nešto ne radi

| Problem | Rješenje |
|---|---|
| "Link vodi na web stranicu, a ne na video" | Link nije direktan. Stavi video na Google Drive s pristupom *Anyone with the link* i daj taj link. |
| "YouTube je blokirao preuzimanje" | Normalno je, YouTube blokira GitHub servere. Koristi materijal s Vyro ili Google Drive. |
| Google Drive javlja grešku | Provjeri da je dijeljenje **Anyone with the link**, a ne *Restricted*. |
| Instagram objava ne uspijeva | Račun mora biti Professional (Creator ili Business). Ako jest, u Bufferu ga isključi i ponovno poveži. |
| "Queue limit reached" | Besplatni Buffer plan drži ograničen broj objava u redu. Pričekaj da se objave ili obriši stare u Bufferu. |
| Klipovi nisu dobri momenti | U `config.yaml` dodaj riječi u `hype_words` ili povećaj `clips_per_video` pa biraj najbolje. |
| Workflow 3 se ne pokreće | GitHub gasi zakazane workflowe nakon 60 dana bez aktivnosti. Actions → 3 → Enable. |

Detalje greške uvijek vidiš u **Actions** → klik na crveno pokretanje → klik na korak koji je pao.

## Realno o zaradi

- Zadnje MrBeast kampanje plaćale su oko **1 $ na 1.000 pregleda**: 100.000 pregleda je oko 100 $.
- Budžet kampanje (npr. 25.000 $) dijele svi kliperi. Kad se potroši, kampanja završava.
- Plaća se samo za klipove koje Vyro odobri prema pravilima kampanje.
- Najviše zarađuju brzi kliperi s dobrim izborom momenata. Tvoj pregled klipova je zato važan dio posla.

## Što je unutra

```
config.yaml                 ← postavke (smiješ mijenjati)
clipper/fetch.py            preuzimanje materijala
clipper/transcribe.py       prepoznavanje govora (Whisper)
clipper/highlights.py       izbor najboljih momenata
clipper/render.py           vertikalni video + titlovi
clipper/hosting.py          upload na Cloudinary
clipper/buffer.py           objava preko Buffer API-ja
clipper/main.py             povezuje sve s GitHub Issuesima
.github/workflows/          4 automatska procesa
```

## 🤖 AI odabir klipova

Kad postoji secret **`GEMINI_API_KEY`**, workflow **1. Napravi klipove** daje cijeli transkript AI-ju. AI:
- bira momente koji imaju smisla bez konteksta (počinju i završavaju na granici misli)
- odbacuje loše (prekinute, osjetljive, krivo prepoznat govor, reklame)
- piše **hook na videu** i **opis objave**
- daje ocjenu 1–10, a klipovi ispod `ai_min_ocjena` se ne prave

Takvi klipovi imaju 🤖 u naslovu Issuea i **5. Dnevne objave** ih objavljuju same, najbolje ocijenjene prve.
Ručni opisi u `opisi:` i dalje imaju prednost.

**Ključ (besplatno):** aistudio.google.com/apikey → Create API key → zalijepi ga u
GitHub → Settings → Secrets and variables → Actions → New secret, ime `GEMINI_API_KEY`.
Provjeri s workflowom **0. Provjeri postavke**.

Kad mijenjaš kampanju, promijeni `brief:` i `hashtags:` u `config.yaml`.
