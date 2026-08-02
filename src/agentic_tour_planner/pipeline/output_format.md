# Output Format: Detailed Place-by-Place Itinerary

This is the canonical, fixed output contract for the "detailed places" mode. The
planner MUST always produce the same shape so the rich CLI renderer is stable and
predictable. The data is returned as **JSON** (not prose) and rendered by the
CLI with colour, bold and italics.

Produce the itinerary **day by day**, following the journey from the point the
traveller starts each day through to the last place on that day's route. List
places within a day in visiting order.

## JSON schema

```json
{
  "days": [
    {
      "day": 1,
      "theme": "<day theme>",
      "places": [
        {
          "name": "<Place Name>",
          "description": "<≈200 words: history, locality, important things>",
          "opening_closing": "<REAL opening & closing from the tool data, or 'Not available'>",
          "best_time": "<best time window / lighting / crowd note>",
          "transport": "<available transport options with fare>",
          "key_note": "<≈100 words, 2-3 sentences concise summary>",
          "keywords": [
            {"text": "<exact term as it appears in description>", "category": "place"},
            {"text": "<e.g. 3,650 m / altitude 12,000 ft>", "category": "altitude"},
            {"text": "<famous person name>", "category": "person"},
            {"text": "<deity / religious figure>", "category": "deity"},
            {"text": "<other important term>", "category": "other"}
          ],
          "is_optional": false
        },
        {
          "name": "<Optional Place Name>",
          "description": "<≈200 words: history, locality, important things>",
          "key_note": "<≈200 words concise summary>",
          "keywords": [
            {"text": "<exact term>", "category": "place"}
          ],
          "is_optional": true
        }
      ]
    }
  ]
}
```

## Rules

- The user selects **N places per day** (e.g. 3–5). Those **N CORE places are
  MANDATORY** (`is_optional: false`) and each must have the full set of fields
  (description, opening_closing, best_time, transport, key_note).
- **Everything else is optional** except the N core place names. If real data is
  unavailable, write `"Not available"` — never invent times or fares.
- Optional extra places (`is_optional: true`) follow the core places. They use a
  **reduced** shape (description + key_note only) and MUST NOT include
  `opening_closing` or `transport`. Optional places may be skipped entirely.
- Descriptions are **≈200 words** (not 300/500). Key notes are ≈100 words (2-3
  sentences). Keep them tight and vivid.
- `keywords` is MANDATORY for every place. List the important terms that appear
  **verbatim** inside that place's `description`, each tagged with a `category`:
  `place` (locations, landmark names), `altitude` (elevation, height in m/ft),
  `person` (famous/historical people), `deity` (gods, saints, religious figures),
  `other` (any other locally important term). The renderer colours these by
  category. The `text` values must match the description **exactly** so the
  renderer's highlighter can find them.
- **Emphasis is welcome**: in `description`, `key_note`, `transport`, and
  `best_time`, wrap important real names (places, mountains, lakes, people,
  dishes, prices) in `**bold**` and add *italics* for atmospheric or secondary
  emphasis. This makes the rendered CLI/UI output lively. Only wrap terms that
  actually appear in the surrounding sentence, and keep the emphasis sparing so
  prose still reads naturally.
- The values in the `keywords` array are then ALSO colour-coded by the renderer;
  there is no conflict with the `**bold**` markdown above.
- Follow the route end-to-end; do not reorder places illogically.
- Use ONLY the REAL opening hours and fares supplied in the tool-output section;
  do not guess or hallucinate them.
- Return valid JSON only (no surrounding markdown fences).
