# deck — English research report (PDF)

This directory turns the repository's findings into something a developer, a
lender or an investment committee can read in fifteen minutes. Nothing is
computed here: every number is read from `../results/`.

## Output

| File | Contents |
|---|---|
| `out/bess-revenue-stack-en.pdf` | 14 pages, 780×540 pt, English |

## Structure

```
Cover / Summary (the five results) / Method (what is and is not modelled)
1  The stack      the waterfall: £3.93m -> £1.42m
2  The shortcuts  wear at zero / reserve headroom / forecasting /
                  flat efficiency / one wear price per service
3  Robustness     moving-block bootstrap of every headline
4  Method         the three modelling choices behind the numbers
   Implications   what to change in a revenue model, ranked by worth
5  Reference      how to read this, and where the data comes from
Back cover
```

## Building it

```bash
python deck/make_figures.py                              # results/* -> deck/fig/*.png
cd deck && ./render.sh slides.html out/bess-revenue-stack-en.pdf
```

Dependencies: `pandas`, `matplotlib`, `pillow` (already in the repository's
`requirements.txt`). The PDF step uses headless Chrome — no Playwright, no
LaTeX.

## Files

| File | Role |
|---|---|
| `slides.html` | The deck. One `<section class="slide">` per page |
| `deck.css` | Layout contract: 780×540 pt, type scale, colour tokens |
| `deck.mplstyle` | matplotlib theme for the figures |
| `palette.py` | Colour tokens (blue = fact, red = look here, grey = context) |
| `make_figures.py` | Seven figures, reading `../results/` only |
| `render.sh` | HTML → PDF |
| `img/` | Photographs (2400px) and `credits.json` |
| `fig/` | Generated figures (reproducible with `make_figures.py`) |

## Conventions this deck follows

1. **Every headline is a judgement**, not a label. Read the headlines top to
   bottom and the argument holds without the figures.
2. **One claim per page.** If a headline runs to three lines the sentence is
   too long, not the type too large.
3. **Fact, inference and caveat are separated** by colour and by position:
   the claim is in the headline, the qualification in the read-out line.
4. **Red appears once per page**, on the thing the reader should look at.
5. **Every figure carries its unit and its source.**

Format specification: `workspace/skills/report-deck-{workflow,writing,design}.md`

## Photographs

Both photographs come from Wikimedia Commons under reusable licences and are
included in `deck/img/`, so a clone reproduces the PDF as laid out here. Each
is credited on the page it appears on, and in `img/credits.json`.

| Page | Subject | Photographer | Licence |
|---|---|---|---|
| Cover | Leslie Battery Storage, Fife — a GB grid-scale battery site | Bill Kasman | CC BY-SA 2.0 (**cropped**) |
| Back cover | Stockbridge dampers on a 400 kV line | Adrian Pingstone | Public domain |

## Licence

**Text and figures**: CC BY 4.0. **Code**: MIT, as for the repository.

**Photographs keep their own licences** — they are collected here, not
absorbed into the deck's licence. In particular the cover photograph is a
crop of a CC BY-SA 2.0 work, so that crop is itself available under
CC BY-SA 2.0; the ShareAlike condition applies to the image, not to the text
and figures around it.
