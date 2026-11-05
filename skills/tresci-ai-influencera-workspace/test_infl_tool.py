#!/usr/bin/env python3
"""Testy regresji dla infl_tool.py z iteracji 2 skilla tresci-ai-influencera.

Narzędzie jest wklejone w SKILL.md, więc test najpierw je stamtąd wypakowuje
(tak samo jak krok 0 skilla), a potem sprawdza:
  - check łapie 7 rozjazdów, które w iteracji 1 przechodziły bez słowa,
  - check nie zgłasza fałszywych alarmów na czystym kalendarzu,
  - stats nie wyciąga wniosku o porze, gdy pora pokrywa się z formatem,
  - plan przenosi publikacje z dni delikatnych i nadaje unikalne id.

Uruchomienie: python3 -I skills/tresci-ai-influencera-workspace/test_infl_tool.py
(działa też pod pytest).
"""
import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", "tresci-ai-influencera", "SKILL.md")

CARD = """# Lena: karta persony

## Kotwice
- trigger: lnx_woman
- cechy: shoulder-length copper hair; green eyes; light freckles
- miejsca: Kraków Kazimierz café; Wisła boulevards; minimalist loft apartment; vintage shop on Józefa street
- stroje: oversized beige knit sweater; black leather jacket and jeans; cream trench coat; chunky green cardigan
- emoji_max: 3
- zakazane: polityka; dieta cud; kryptowaluty
- sprzedaz_max: 1/6

## Podstawy
- Lena, 26 lat
"""

HOOKS = ["Oversize nie musi wyglądać jak piżama", "Tak powstaje moje zdjęcie, krok po kroku", "Kawa na mieście czy w domu? Bez kombinowania",
         "Przestań prasować oversize, serio", "Miałam dziś wyjść o 8. Wyszłam o 11.", "POV: jesteś AI i pierwszy raz widzisz śnieg",
         "Wszyscy kupują nowe. Ja wróciłam do lumpeksu", "Mały hack na mokre buty", "Jedna kurtka, zero nudy", "Zieleń bez efektu choinki",
         "Dzianina, która nie gryzie", "Szalik zamiast biżuterii", "Jesień bez czerni", "Ten kolor ratuje listopad", "Golf czy szalik? Wybierz",
         "Kulisy: co AI psuje najczęściej", "Rano w Krakowie pachnie kawą", "Mniej rzeczy, więcej pomysłów", "Lumpeks bez stresu",
         "Moja zasada trzech kolorów", "Buty, które nie męczą wzroku", "Tydzień w jednym płaszczu", "Kardigan jako kurtka", "Bez prasowania, serio",
         "Co mówi twój sweter", "Ciepło i bez kokonu", "Brąz to nowa czerń", "Jedna torba na wszystko", "Krem, beż i miedź", "Wieczór w lofcie",
         "Kawa i plan na dziś", "Deszcz? Mam na to strój", "Sweter po bracie", "Wełna czy akryl? Sprawdzam",
         "Miedziane włosy lubią zieleń", "Płaszcz do kostek bez dramatu", "Kolczyki zamiast nowego swetra", "Czapka, która nie niszczy fryzury",
         "Rękawiczki jako akcent", "Kratka wraca na ulice", "Sztruks bez efektu dziadka", "Biel zimą działa", "Plecak do eleganckiego płaszcza",
         "Pasek na sweter, serio", "Skarpetki widać i dobrze", "Mgła nad Wisłą i ja", "Bulwary o zmroku", "Loft w niedzielnym świetle"]


def extract(dst):
    s = open(SKILL, encoding="utf-8").read()
    code = s.rsplit("# >>> infl_tool.py", 1)[1].split("# <<< infl_tool.py")[0]
    open(dst, "w", encoding="utf-8").write(code)


def write_csv(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:  # zamknięty plik, zanim check go przeczyta
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def run(tool, *args):
    p = subprocess.run([sys.executable, "-I", tool, *args], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def clean_calendar(tool, d):
    """Szkielet z plan + uzupełnione teksty i prompty, tak żeby check dał OK."""
    card = os.path.join(d, "karta.md")
    open(card, "w", encoding="utf-8").write(CARD)
    sk = os.path.join(d, "szkielet.csv")
    code, out = run(tool, "plan", "--start", "2026-11-16", "--days", "14", "--karta", card, "--out", sk, "--dzis", "2026-11-05")
    assert code == 0, out
    rows = list(csv.DictReader(open(sk, encoding="utf-8")))
    cols = list(rows[0])
    hi = 0
    for r in rows:
        r["hook"] = ["", "Serio: ", "Uwaga: "][hi // len(HOOKS)] + HOOKS[hi % len(HOOKS)]
        hi += 1
        r["caption"] = f"{r['hook']}. Zapisz na później."
        r["hashtagi"] = "#jesiennestylizacje #secondhand #LenaStyluje" if r["platforma"] != "x" else ""
        if r["prompt_obrazu"]:
            r["prompt_obrazu"] = (r["prompt_obrazu"].replace("[CZYNNOŚĆ]", f"looking at the camera, variant {hi}")
                                  .replace("[APARAT]", "shot on 35mm film").replace("[NASTRÓJ]", "calm mood"))
        if r["format"] == "reel":
            r["prompt_wideo"] = "slow push-in, she smiles, 4 s"
        if r["filar"] == "sprzedaż":
            r["reklama"] = "afiliacja: Wełniak.pl"
            r["caption"] = f"[reklama] Afiliacja z Wełniak.pl. {r['hook']}."
    path = os.path.join(d, "kalendarz.csv")
    write_csv(path, cols, rows)
    return path, card, rows, cols


def test_all():
    with tempfile.TemporaryDirectory() as d:
        d = os.environ.get("INFL_TEST_DIR") or d
        tool = os.path.join(d, "infl_tool.py")
        extract(tool)

        # 1. czysty kalendarz: zero błędów, bez ostrzeżeń o sesjach, dniach i reklamie
        path, card, rows, cols = clean_calendar(tool, d)
        code, out = run(tool, "check", path, "--karta", card, "--dzis", "2026-11-05")
        assert code == 0 and "WYNIK: OK" in out and "OSTRZEŻENIA" not in out, out
        for frag in ("pusty caption", "a sesja", "hook mówi", "osobiste użycie", "z datą sprzed dziś", "Powtórzone id"):
            assert frag not in out, (frag, out)

        # 2. wstrzyknięte rozjazdy z iteracji 1
        feed = [i for i, r in enumerate(rows) if r["platforma"] == "instagram" and r["format"] in ("post", "karuzela", "reel")]
        post = next(i for i in feed if rows[i]["format"] == "post")
        car = next(i for i in feed if rows[i]["format"] == "karuzela")
        reel = next(i for i in feed if rows[i]["format"] == "reel")
        rows[post]["hook"] = "3 swetry z lumpeksu, które wyglądają na drogie"            # lista w jednym zdjęciu
        rows[post]["filar"] = "sprzedaż"                                                  # sprzedaż bez wpisu w reklama
        rows[post]["reklama"] = "brak"
        rows[post]["caption"] = rows[post]["hook"] + ". Opis bez oznaczenia."
        wd = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
        from datetime import date
        dd = date.fromisoformat(rows[car]["data"])
        rows[car]["hook"] = f"{wd[(dd.weekday() + 2) % 7]} w Kazimierzu wygląda tak"         # zły dzień tygodnia
        ses_outfit = rows[reel]["sesja"].split("|")[1].strip()
        other = next(o for o in ("cream trench coat", "chunky green cardigan", "black leather jacket and jeans") if o != ses_outfit)
        rows[reel]["prompt_obrazu"] = rows[reel]["prompt_obrazu"].replace(ses_outfit, other)  # strój niezgodny z sesją
        rows[reel]["reklama"] = "afiliacja: Wełniak.pl"
        rows[reel]["caption"] = "[reklama] Afiliacja z Wełniak.pl. Ten sweter noszę od tygodnia i dalej jest super."  # deklaracja użycia
        rows[feed[-1]]["caption"] = ""                                                    # pusty opis
        rows[1]["id"] = rows[0]["id"]                                                     # duplikat id
        rows[2]["data"] = "2026-11-03"                                                    # data z przeszłości
        bad = os.path.join(d, "defekty.csv")
        write_csv(bad, cols, rows)
        code, out = run(tool, "check", bad, "--karta", card, "--dzis", "2026-11-05")
        assert code == 1, out
        for frag in ("hook obiecuje listę", "filar 'sprzedaż', a reklama", "hook mówi", f"a sesja '{ses_outfit}'",
                     "osobiste użycie", "pusty caption", "Powtórzone id", "z datą sprzed dziś"):
            assert frag in out, (frag, out)

        # 3. "Po piątku trzynastego" to nie jest dzień publikacji
        rows2 = [dict(r) for r in csv.DictReader(open(path, encoding="utf-8"))]
        rows2[3]["hook"] = "Po piątku trzynastego należy ci się coś ciepłego"
        p2 = os.path.join(d, "piatek.csv")
        write_csv(p2, cols, rows2)
        code, out = run(tool, "check", p2, "--karta", card, "--dzis", "2026-11-05")
        assert "hook mówi" not in out, out

        # 4. stats: pora = format, więc bez wniosku o porze
        res = os.path.join(d, "wyniki.csv")
        with open(res, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Publish time", "Post type", "Description", "Reach", "Likes", "Comments", "Saves", "Shares", "Follows"])
            for i in range(6):
                w.writerow([f"2026-11-{2 + i:02d} 19:3{i}", "Reel", "Tak powstaje moje zdjęcie", 4000, 250, 30, 40, 40, 15])
            for i in range(4):
                w.writerow([f"2026-11-{9 + i:02d} 18:3{i}", "Image", "3 swetry z lumpeksu", 2000, 70, 5, 8, 7, 3])
        code, out = run(tool, "stats", res, "--platforma", "instagram")
        assert code == 0, out
        assert "pory pokrywają się z formatami" in out and "Pory nie da się ocenić" in out, out
        assert "Pora z najlepszą medianą" not in out, out
        assert "Typ hooka" in out, out

        # 5. plan: dni delikatne i id
        sk = os.path.join(d, "listopad.csv")
        code, out = run(tool, "plan", "--start", "2026-11-02", "--days", "14", "--karta", card, "--out", sk, "--dzis", "2026-11-05")
        assert code == 0 and "UWAGA: start" in out and "Dni delikatne" in out, out
        rows3 = list(csv.DictReader(open(sk, encoding="utf-8")))
        for day in ("2026-11-02", "2026-11-11"):
            left = [r for r in rows3 if r["data"] == day]
            assert left and all(r["format"] == "story" for r in left), (day, left)
        ids = [r["id"] for r in rows3]
        assert len(ids) == len(set(ids)) and ids[0].startswith("lena-20261102-"), ids[:3]
        pairs = [tuple(x.strip() for x in r["sesja"].split(":", 1)[1].split("|")[:2]) for r in rows3 if r["sesja"]]
        assert len(set(pairs)) == len(dict.fromkeys(r["sesja"] for r in rows3 if r["sesja"])), "pary miejsce+strój się powtarzają"
    print("OK: wszystkie testy przeszły")


if __name__ == "__main__":
    test_all()
